#!/usr/bin/env python3
from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from integrations.isaac_lab_robotis_omx.external_callback import register

    register()
    from scripts.lerobot_isaac_lab_robomimic_train import _isaac_lab_path
    isaac_lab = _isaac_lab_path(sys.argv)
    script = isaac_lab / "scripts" / "imitation_learning" / "robomimic" / "robust_eval.py"
    sys.argv[0] = str(script)
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
