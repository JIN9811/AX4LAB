"""
File purpose:
- Load and merge YAML configuration files used by the framework.

Key classes/functions:
- load_yaml
- load_all_configs

Inputs/outputs:
- Input: YAML file paths
- Output: dictionary-based configuration bundle

Dependencies:
- pathlib.Path
- yaml.safe_load

Modification guide:
- Safe places to edit: new config files and default-merging behavior
- Risky places to edit: return schema consumed across modules
- Related files: app/bootstrap.py, configs/*.yaml
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from utils.installation_profile import (
    INSTALLATION_PROFILE_ENV,
    apply_installation_profile,
    load_installation_profile,
)
from utils.runtime_paths import RuntimePaths
from utils.yaml_cache import read_yaml


def load_yaml(path: Path) -> dict[str, Any]:
    """Load one YAML file and return an empty dict if the file is empty."""
    loaded = read_yaml(path) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"YAML root must be an object: {path}")
    return loaded


def load_all_configs(
    config_dir: Path,
    *,
    paths: RuntimePaths | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Load YAML files and optionally apply the installation resource profile."""
    merged: dict[str, Any] = {}
    for path in sorted(config_dir.glob("*.yaml")):
        merged[path.stem] = load_yaml(path)
    if paths is None:
        selected_environment = environ if environ is not None else os.environ
        if str(selected_environment.get(INSTALLATION_PROFILE_ENV) or "").strip():
            raise ValueError(
                f"RuntimePaths are required to apply {INSTALLATION_PROFILE_ENV}; "
                "the selected installation profile was not ignored"
            )
        return merged
    return apply_installation_profile(
        merged,
        load_installation_profile(paths, environ=environ),
    )
