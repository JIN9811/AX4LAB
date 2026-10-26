"""Settings updates preserve the existing shared profile envelope."""
import importlib
import json
import multiprocessing

import pytest


@pytest.fixture
def settings():
    class Settings:
        def __getattr__(self, attribute):
            name = "utils.equipment_computer_use_settings"
            assert importlib.util.find_spec(name) is not None, "settings store is missing"
            return getattr(importlib.import_module(name), attribute)
    return Settings()


def test_missing_profile_stays_legacy_without_writing(settings, tmp_path):
    path = tmp_path / "prefs.json"
    assert settings.load_profile_settings(path, "A")["execution_mode"] == "skill_flow"
    assert not path.exists()


def test_partial_updates_preserve_other_profiles_and_unknown_keys(settings, tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"version": 7, "profiles": {"A": {"vision_link_enabled": False, "future": {"x": 1}}, "B": {"keep": 2}}}))
    settings.save_profile_settings(path, "A", {"execution_mode": "computer_use", "computer_use": {"max_turns": 3}})
    result = settings.save_profile_settings(path, "A", {"computer_use": {"request_timeout_s": 10}})
    assert result["computer_use"] == {"max_turns": 3, "request_timeout_s": 10.0, "frame_max_age_s": 150.0}
    assert result["execution_mode"] == "computer_use"
    data = json.loads(path.read_text())
    assert data["version"] == 7
    assert data["profiles"]["B"] == {"keep": 2}
    assert data["profiles"]["A"]["future"] == {"x": 1}
    assert data["profiles"]["A"]["vision_link_enabled"] is False
    assert settings.load_profile_settings(path, "B")["execution_mode"] == "skill_flow"


def test_invalid_update_does_not_replace_settings(settings, tmp_path):
    path = tmp_path / "prefs.json"
    settings.save_profile_settings(path, "A", {})
    original = path.read_bytes()
    with pytest.raises(ValueError):
        settings.save_profile_settings(path, "A", {"computer_use": {"max_turns": True}})
    assert path.read_bytes() == original


@pytest.mark.parametrize("contents", ['{', '[]', '{"profiles":[]}', '{"profiles":{"A":null}}',
                                      '{"profiles":{"A":{},"A":{"keep":true}}}',
                                      '{"profiles":{"A":{"future":NaN}}}'])
def test_corrupt_existing_store_is_not_overwritten(settings, tmp_path, contents):
    path = tmp_path / "prefs.json"
    path.write_text(contents)
    with pytest.raises(ValueError):
        settings.save_profile_settings(path, "A", {})
    assert path.read_text() == contents


def _save_in_process(path, field):
    from utils.equipment_computer_use_settings import save_profile_settings
    save_profile_settings(path, "A", {field: field})


def test_concurrent_process_updates_do_not_lose_keys(settings, tmp_path):
    path = tmp_path / "prefs.json"
    settings.save_profile_settings(path, "A", {})
    context = multiprocessing.get_context("fork")
    processes = [context.Process(target=_save_in_process, args=(path, f"field_{i}")) for i in range(12)]
    for process in processes: process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    data = json.loads(path.read_text())["profiles"]["A"]
    assert all(data[f"field_{i}"] == f"field_{i}" for i in range(12))
