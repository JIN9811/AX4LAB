"""Explicit root provenance and bounded environments for fresh interpreters."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from utils.installation_profile import (
    InstallationProfile,
    installation_metadata,
    load_installation_profile,
)
from utils.runtime_paths import RuntimePaths, load_paths


def path_metadata(
    paths: RuntimePaths,
    *,
    profile: InstallationProfile | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Require reproducible metadata, never invent or discover a private binding."""
    selected_environment = environ if environ is not None else os.environ
    layout = Path(selected_environment.get('ATR_LAYOUT_CONFIG') or
                  paths.runtime_root / 'configs/repository_layout.json').expanduser().resolve()
    selected = selected_environment.get('ATR_PATH_BINDINGS')
    binding = Path(selected).expanduser().resolve() if selected else None
    description = f'ATR_LAYOUT_CONFIG={layout}, ATR_PATH_BINDINGS={binding}'
    try:
        reproduced = load_paths(layout, bindings_file=binding)
    except (OSError, ValueError) as exc:
        raise ValueError(f'Cannot reproduce runtime metadata ({description}): {exc}') from exc
    if reproduced != paths:
        raise ValueError(f'Conflicting runtime metadata ({description}); select metadata matching the parent binding')
    metadata = {'ATR_LAYOUT_CONFIG': str(layout)}
    if binding is not None:
        metadata['ATR_PATH_BINDINGS'] = str(binding)
    metadata.update(installation_metadata(
        profile or load_installation_profile(paths, environ=selected_environment)
    ))
    return metadata


def process_environment(*, desktop: bool = False) -> dict[str, str]:
    """Do not inherit Python import controls, credentials or arbitrary overrides."""
    keys = ('HOME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'VIRTUAL_ENV')
    if desktop:
        keys += ('DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR', 'XDG_SESSION_TYPE',
                 'WAYLAND_DISPLAY')
    env = {key: os.environ[key] for key in keys if key in os.environ}
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
               MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1', MPLBACKEND='Agg')
    return env
