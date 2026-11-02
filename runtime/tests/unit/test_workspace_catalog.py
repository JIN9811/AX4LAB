from pathlib import Path

import pytest
import yaml


def _descriptor(identity: str, *, version: str = "1.2.3") -> dict:
    return {
        "schema": "ax4lab.workspace.v1",
        "id": identity,
        "version": version,
        "label": identity.replace("_", " ").title(),
        "icon": "icon.svg",
        "defaults": {},
        "fields": [],
        "actions": ["preview"],
        "output_kinds": ["mesh"],
    }


def _install(root: Path, folder: str, descriptor: dict | None = None) -> Path:
    module_root = root / folder
    module_root.mkdir()
    (module_root / "module.yaml").write_text(
        yaml.safe_dump(descriptor or _descriptor(folder)), encoding="utf-8"
    )
    (module_root / "provider.py").write_text(
        'raise RuntimeError("provider imported during discovery")\n', encoding="utf-8"
    )
    (module_root / "icon.svg").write_text("<svg/>", encoding="utf-8")
    return module_root


def _validate_workspace(descriptor: dict) -> dict:
    if descriptor.get("schema") != "ax4lab.workspace.v1":
        raise ValueError("Unsupported workspace schema")
    return descriptor


def test_discovers_third_module_without_registration_or_provider_import(tmp_path):
    from workspaces.catalog import discover_modules

    module_root = _install(tmp_path, "third_module")

    modules, errors = discover_modules(tmp_path, _validate_workspace)

    assert errors == []
    assert modules == [
        {
            "id": "third_module",
            "version": "1.2.3",
            "root": module_root.resolve(),
            "descriptor_path": (module_root / "module.yaml").resolve(),
            "provider_path": (module_root / "provider.py").resolve(),
            "icon_path": (module_root / "icon.svg").resolve(),
            "descriptor": _descriptor("third_module"),
        }
    ]


def test_duplicate_ids_are_all_excluded_and_malformed_module_is_isolated(tmp_path):
    from workspaces.catalog import discover_modules

    _install(tmp_path, "good")
    _install(tmp_path, "copy_one", _descriptor("duplicate"))
    _install(tmp_path, "copy_two", _descriptor("duplicate"))
    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / "module.yaml").write_text("id: [not valid", encoding="utf-8")

    modules, errors = discover_modules(tmp_path, _validate_workspace)

    assert [module["id"] for module in modules] == ["good"]
    assert len(errors) == 2
    assert {error["module"] for error in errors} == {"duplicate", "malformed"}
    assert next(error for error in errors if error["module"] == "duplicate")["message"] == "Duplicate module ID"


def test_huge_integer_in_malformed_module_does_not_hide_good_module(tmp_path):
    from workspaces.catalog import discover_modules
    from workspaces.fields import normalize_fields

    _install(tmp_path, "good")
    malformed = _descriptor("malformed")
    malformed["fields"] = [
        {"key": "ratio", "label": "Ratio", "type": "number", "min": 0, "max": 10}
    ]
    malformed["defaults"] = {"ratio": 10**400}
    _install(tmp_path, "malformed", malformed)

    def validate(descriptor):
        descriptor = _validate_workspace(descriptor)
        descriptor["defaults"] = normalize_fields(
            descriptor["fields"], descriptor["defaults"], {}
        )
        return descriptor

    modules, errors = discover_modules(tmp_path, validate)

    assert [module["id"] for module in modules] == ["good"]
    assert len(errors) == 1
    assert errors[0]["module"] == "malformed"
    assert "bounds" in errors[0]["message"]


def test_validator_overflow_is_isolated_from_good_module(tmp_path):
    from workspaces.catalog import discover_modules

    _install(tmp_path, "good")
    _install(tmp_path, "overflow")

    def validate(descriptor):
        descriptor = _validate_workspace(descriptor)
        if descriptor["id"] == "overflow":
            raise OverflowError("synthetic arithmetic overflow")
        return descriptor

    modules, errors = discover_modules(tmp_path, validate)

    assert [module["id"] for module in modules] == ["good"]
    assert errors == [
        {"module": "overflow", "message": "synthetic arithmetic overflow"}
    ]


@pytest.mark.parametrize("unsafe_key", ["provider", "python_import", "script", "shell", "equation"])
def test_descriptor_cannot_supply_executable_metadata(tmp_path, unsafe_key):
    from workspaces.catalog import discover_modules

    descriptor = _descriptor("unsafe")
    descriptor[unsafe_key] = "malicious.payload"
    _install(tmp_path, "unsafe", descriptor)

    modules, errors = discover_modules(tmp_path, _validate_workspace)

    assert modules == []
    assert errors == [{"module": "unsafe", "message": f"Unsafe module metadata key: {unsafe_key}"}]


@pytest.mark.parametrize("escaped_asset", ["module.yaml", "provider.py", "icon.svg"])
def test_descriptor_provider_and_icon_symlinks_cannot_escape(tmp_path, escaped_asset):
    from workspaces.catalog import discover_modules

    outside = tmp_path / "outside"
    outside.mkdir()
    external = outside / escaped_asset
    if escaped_asset == "module.yaml":
        external.write_text(yaml.safe_dump(_descriptor("escaped")), encoding="utf-8")
    else:
        external.write_text("external", encoding="utf-8")
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    module_root = _install(catalog_root, "escaped")
    (module_root / escaped_asset).unlink()
    (module_root / escaped_asset).symlink_to(external)

    modules, errors = discover_modules(catalog_root, _validate_workspace)

    assert modules == []
    assert len(errors) == 1
    assert errors[0]["module"] == "escaped"
    assert "escape" in errors[0]["message"].lower()


def _all_field_types():
    return [
        {"key": "ratio", "label": "Ratio", "type": "number", "min": 0.1, "max": 2.0},
        {"key": "count", "label": "Count", "type": "integer", "min": 1, "max": 8},
        {"key": "mode", "label": "Mode", "type": "enum", "options": ["fast", "exact"]},
        {"key": "enabled", "label": "Enabled", "type": "boolean"},
        {"key": "name", "label": "Name", "type": "text"},
        {"key": "size", "label": "Size", "type": "vector", "length": 3, "min": 0.1, "max": 100.0},
        {
            "key": "quality",
            "label": "Quality",
            "type": "enum",
            "options": ["preview", "final"],
            "visible_when": {"field": "enabled", "equals": True},
        },
        {
            "key": "note",
            "label": "Note",
            "type": "text",
            "visible_when": {"field": "mode", "in": ["fast", "exact"]},
        },
    ]


def _all_defaults():
    return {
        "ratio": 1.0,
        "count": 4,
        "mode": "fast",
        "enabled": False,
        "name": "cell",
        "size": [10.0, 10.0, 10.0],
        "quality": "preview",
        "note": "",
    }


def test_normalizes_number_integer_enum_boolean_text_and_vector_fields():
    from workspaces.fields import normalize_fields

    normalized = normalize_fields(
        _all_field_types(),
        _all_defaults(),
        {
            "ratio": 1.5,
            "count": 6,
            "mode": "exact",
            "enabled": True,
            "name": "updated",
            "size": [20, 30.5, 40],
            "quality": "final",
        },
    )

    assert normalized == {
        "ratio": 1.5,
        "count": 6,
        "mode": "exact",
        "enabled": True,
        "name": "updated",
        "size": [20, 30.5, 40],
        "quality": "final",
        "note": "",
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda fields, defaults, values: fields[0].update(min=float("-inf")), "finite"),
        (lambda fields, defaults, values: values.update(ratio=float("nan")), "finite"),
        (lambda fields, defaults, values: defaults.pop("count"), "default"),
        (lambda fields, defaults, values: values.update(unknown=1), "unknown"),
        (
            lambda fields, defaults, values: fields[-1].update(
                visible_when={"field": "mode", "script": "return true"}
            ),
            "visible_when",
        ),
    ],
)
def test_rejects_nonfinite_bounds_missing_defaults_unknown_values_and_executable_visibility(
    mutation, message
):
    from workspaces.fields import normalize_fields

    fields, defaults, values = _all_field_types(), _all_defaults(), {}
    mutation(fields, defaults, values)

    with pytest.raises(ValueError, match=message):
        normalize_fields(fields, defaults, values)


def test_visibility_does_not_bypass_authoritative_value_validation():
    from workspaces.fields import normalize_fields

    defaults = _all_defaults()
    defaults["quality"] = "not-an-option"

    with pytest.raises(ValueError, match="quality"):
        normalize_fields(_all_field_types(), defaults, {})


def test_arbitrary_precision_integer_uses_bounds_not_float_finiteness():
    from workspaces.fields import normalize_fields

    fields = [
        {"key": "ratio", "label": "Ratio", "type": "number", "min": 0, "max": 10}
    ]

    with pytest.raises(ValueError, match="bounds"):
        normalize_fields(fields, {"ratio": 10**400}, {})


def test_non_string_field_type_is_rejected_as_malformed_metadata():
    from workspaces.fields import normalize_fields

    fields = _all_field_types()
    fields[0]["type"] = []

    with pytest.raises(ValueError, match="field type"):
        normalize_fields(fields, _all_defaults(), {})
