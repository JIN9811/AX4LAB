"""Linux profile preferences: atomic replacement under a stable process lock."""
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import tempfile

from Pyautogui_server_for_window.bridge.computer_use_contract import ComputerUseError, normalize_settings


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate settings key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Non-finite settings value")


def _read(path):
    if not path.exists():
        return {"profiles": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
    except ValueError:
        raise ComputerUseError("invalid_settings_store", "Settings store is malformed") from None
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
        raise ComputerUseError("invalid_settings_store", "Settings profiles must be an object")
    if any(not isinstance(value, dict) for value in data["profiles"].values()):
        raise ComputerUseError("invalid_settings_store", "Profile preferences must be an object")
    return data


def _profile_id(profile_id):
    if not isinstance(profile_id, str) or not profile_id.strip() or len(profile_id) > 128:
        raise ComputerUseError("invalid_profile", "Profile ID is required")


def load_profile_settings(path: Path, profile_id: str) -> dict:
    """Read a complete atomic snapshot without creating a file or enabling a mode."""
    _profile_id(profile_id)
    raw = _read(Path(path))["profiles"].get(profile_id, {})
    return {**deepcopy(raw), **normalize_settings(raw)}


def save_profile_settings(path, profile_id, patch) -> dict:
    """Merge one profile under flock; preserve unrelated keys and profiles."""
    _profile_id(profile_id)
    if not isinstance(patch, dict):
        raise ComputerUseError("invalid_settings", "Settings patch must be an object")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        data = _read(path)
        old = data["profiles"].get(profile_id, {})
        merged = {**old, **deepcopy(patch)}
        if "computer_use" in patch and isinstance(patch["computer_use"], dict):
            existing = old.get("computer_use", {})
            if not isinstance(existing, dict):
                raise ComputerUseError("invalid_settings", "Stored computer-use settings are malformed")
            merged["computer_use"] = {**existing, **patch["computer_use"]}
        merged.update(normalize_settings(merged))
        data["profiles"][profile_id] = merged
        # Serialize before opening a temporary file: invalid patches cannot alter disk.
        serialized = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
        fd, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(serialized + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return deepcopy(merged)
