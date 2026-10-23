#!/usr/bin/env python3
from __future__ import annotations

import runpy
import sys
import builtins
from pathlib import Path


def _isaac_lab_path(argv: list[str]) -> Path:
    if "--isaac-lab-path" in argv:
        index = argv.index("--isaac-lab-path")
        value = argv[index + 1]
        del argv[index:index + 2]
    else:
        from utils.runtime_paths import current_paths
        from utils.config_loader import load_all_configs
        paths = current_paths()
        value = load_all_configs(paths.runtime_root / "configs", paths=paths).get("lerobot", {}).get("lerobot", {}).get("isaac_lab_path", "")
    if not value:
        raise ValueError("Configure isaac.lab_root or pass --isaac-lab-path")
    return Path(value).expanduser().resolve()


def _delegate(script_name: str) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from integrations.isaac_lab_robotis_omx.external_callback import register

    register()
    builtins.input = lambda *_args, **_kwargs: "y"
    isaac_lab = _isaac_lab_path(sys.argv)
    script = isaac_lab / "scripts" / "imitation_learning" / "robomimic" / script_name
    sys.argv[0] = str(script)
    runpy.run_path(str(script), run_name="__main__")


def main() -> None:
    _delegate("train.py")


if __name__ == "__main__":
    main()
