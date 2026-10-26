#!/usr/bin/env python3
"""Offline installation diagnostics: no app/SDK/model imports or tool execution.

Explicit --hardware retains separate RealSense enumeration, outside offline
installation acceptance. File presence never certifies hardware readiness.
"""
from __future__ import annotations

import argparse
import importlib
from importlib.machinery import PathFinder
from importlib import metadata
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shlex
import shutil
import sys
from typing import Any
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.runtime_paths import RuntimePaths, current_paths  # noqa: E402

CORE_IMPORTS = [
    "fastapi", "uvicorn", "pydantic", "langgraph", "yaml", "httpx", "json_repair",
    "dotenv", "jinja2", "numpy", "matplotlib", "scipy", "pyarrow", "h5py", "PIL",
    "skimage", "trimesh", "rtree", "gpytorch", "botorch", "paho", "pymcprotocol",
]
DISTRIBUTIONS = {"yaml": "PyYAML", "dotenv": "python-dotenv", "PIL": "Pillow",
                 "skimage": "scikit-image", "paho": "paho-mqtt", "json_repair": "json-repair"}
INTEGRATIONS = ("utm", "realsense", "lerobot", "bambu", "prusa", "slicer", "isaac", "desktop")
_SECRET_KEY = re.compile(r"password|passwd|secret|token|api.?key|access.?code", re.I)
# Path normalization can collapse :// to :/ before an invalid resource is
# reported. Sanitize that form too, not just well-formed endpoint URLs.
_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://?[^\s\"'<>]+")


def redact(value: object) -> str:
    """Sanitize all output, including profile provenance and resource paths."""
    def safe_url(match: re.Match) -> str:
        try:
            raw = re.sub(r":/(?!/)", "://", match.group(), count=1)
            parsed = urlsplit(raw)
            return urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", ""))
        except ValueError:
            return "[redacted URL]"

    text = _URL.sub(safe_url, str(value))
    for key, secret in os.environ.items():
        if secret and _SECRET_KEY.search(key):
            text = text.replace(secret, "[redacted]")
    return text


class Doctor:
    def __init__(self, *, core_only: bool = False, hardware: bool = False,
                 paths: RuntimePaths | None = None, integrations: list[str] | None = None) -> None:
        self.paths = paths or current_paths()
        self.core_only = core_only
        self.hardware = hardware
        self.integrations = set(integrations or [])
        if self.integrations - set(INTEGRATIONS):
            raise ValueError("Unknown integration selection")
        if core_only and (self.integrations or hardware):
            raise ValueError("--core-only cannot be combined with --integration or --hardware")
        if "slicer" in self.integrations:
            self.integrations.remove("slicer")
            self.integrations.update(("bambu", "prusa"))
        self.results: list[dict[str, str]] = []
        self.category = "core"
        self.config: dict[str, Any] = {}

    def add(self, level: str, name: str, detail: object, hint: str = "", *, status: str = "") -> None:
        self.results.append({"level": level, "name": redact(name), "detail": redact(detail),
                             "hint": redact(hint), "category": self.category,
                             "status": status or level})

    def ok(self, name: str, detail: object, hint: str = "") -> None:
        self.add("ok", name, detail, hint)

    def warn(self, name: str, detail: object, hint: str = "") -> None:
        self.add("warn", name, detail, hint)

    def fail(self, name: str, detail: object, hint: str = "") -> None:
        self.add("fail", name, detail, hint)

    def check_core_files(self) -> None:
        required = ("app/main.py", "app/serve.py", "configs/system.yaml", "configs/models.yaml",
                    "configs/devices.yaml", "requirements.txt", "install/install_cli.sh")
        missing = [name for name in required if not (self.paths.runtime_root / name).is_file()]
        if not (self.paths.repository_root / ".env.example").is_file():
            missing.append(".env.example")
        if missing:
            self.fail("core files", "missing: " + ", ".join(missing), "Restore the checkout files.")
        else:
            self.ok("core files", "required repository files are present")
        self.ok("source roots", f"repository={self.paths.repository_root}; runtime={self.paths.runtime_root}; system={self.paths.system_root}")

    def check_python(self) -> None:
        method = self.ok if sys.version_info >= (3, 11) else self.fail
        method("python", f"{sys.version.split()[0]}; executable={sys.executable}; prefix={sys.prefix}")
        venv = self.paths.repository_root / ".venv"
        marker = venv / ".atr-prefix"
        if venv.is_symlink():
            self.fail("virtualenv", "checkout .venv is a symlink; rebuild explicitly")
        elif marker.is_file() and marker.read_text().strip() != str(venv):
            self.fail("virtualenv", "checkout .venv has a moved/stale prefix; rebuild explicitly")
        elif Path(sys.prefix).resolve() != venv:
            self.warn("virtualenv", "active Python is not this checkout's .venv; use install/run_local.sh after setup")
        elif not marker.is_file():
            self.fail("virtualenv", "checkout .venv is unmarked; run bootstrap_linux.sh explicitly")
        else:
            self.ok("virtualenv", "active prefix and checkout ownership marker agree")
        self.warn("environment", ".env exists; values not read" if (self.paths.repository_root / ".env").is_file()
                  else ".env missing; set operator environment before live use")

    def check_imports(self) -> None:
        """Top-level PathFinder avoids dotted parent imports and SDK initialization."""
        missing = []
        for name in CORE_IMPORTS:
            spec = PathFinder.find_spec(name)
            if spec is None:
                missing.append(name)
                continue
            try:
                version = metadata.version(DISTRIBUTIONS.get(name, name))
            except metadata.PackageNotFoundError:
                version = "metadata unavailable"
            origin = spec.origin or ", ".join(spec.submodule_search_locations or [])
            self.ok("package: " + name, f"version={version}; origin={origin}; not imported")
        if missing:
            self.fail("python imports", "missing package specs: " + ", ".join(missing), "Run checkout bootstrap with the frozen core dependencies.")
        else:
            self.ok("python imports", "core package specs present; runtime imports/ABI compatibility unverified")

    def check_source_origins(self) -> None:
        for name in ("app", "utils", "device_bridges"):
            loaded = sys.modules.get(name)
            if loaded is not None:
                origins = [getattr(loaded, "__file__", None)]
                origins = [item for item in origins if item] or list(getattr(loaded, "__path__", []))
            else:
                spec = PathFinder.find_spec(name)
                origins = ([spec.origin] if spec and spec.origin else
                           list(spec.submodule_search_locations or []) if spec else [])
            expected = self.paths.runtime_root / name
            valid = origins and all(Path(item).resolve().is_relative_to(expected) for item in origins)
            (self.ok if valid else self.fail)("source origin: " + name,
                f"observed={origins}; expected={expected}; inspected without import")
        for name, loaded in tuple(sys.modules.items()):
            if name.startswith(("app.", "utils.", "device_bridges.")):
                origin = getattr(loaded, "__file__", None)
                if origin and not Path(origin).resolve().is_relative_to(self.paths.runtime_root):
                    self.fail("source origin: " + name, f"loaded from another checkout: {origin}")

    def check_cli(self) -> None:
        candidates = [Path.home() / ".local/bin/ax4lab"]
        found = shutil.which("ax4lab")
        if found and Path(found) not in candidates:
            candidates.append(Path(found))
        for target in candidates:
            if not target.is_file():
                self.warn("ax4lab launcher", f"not installed: {target}; global alias is optional")
                continue
            bindings = {}
            for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith(("PROJECT_DIR=", "RUNTIME_DIR=")):
                    key, value = line.split("=", 1)
                    try:
                        tokens = shlex.split(value)
                    except ValueError:
                        tokens = []
                    bindings[key] = tokens[0] if len(tokens) == 1 else ""
            if (bindings.get("PROJECT_DIR") == str(self.paths.repository_root)
                    and bindings.get("RUNTIME_DIR") == str(self.paths.runtime_root)):
                self.ok("ax4lab launcher", f"{target}: bound to this checkout")
            else:
                self.warn("ax4lab launcher", f"{target}: another checkout or unverified binding; not modified",
                          "Use this checkout's install/run_local.sh. Global replacement is a separate explicit operation.")

    def check_secrets_policy(self) -> None:
        # Effective Git rules are not claimed: no subprocesses, filters or hooks.
        self.warn("secret ignore policy", ".gitignore present; effective Git ignore policy unverified (no Git executed)"
                  if (self.paths.repository_root / ".gitignore").is_file() else ".gitignore missing; review before storing secrets")

    def load_config(self) -> bool:
        try:
            from utils.config_loader import load_all_configs
            self.config = load_all_configs(self.paths.runtime_root / "configs", paths=self.paths)
        except Exception as exc:
            # YAML/JSON errors can quote arbitrary secret-containing source lines.
            self.fail("configuration", f"{type(exc).__name__}: configuration/profile could not be loaded; source text suppressed",
                      "Check configs/*.yaml and the selected ATR_INSTALL_PROFILE (or installation.local.json).")
            return False
        installation = self.config.get("installation", {})
        self.ok("installation profile", installation.get("profile") or "not configured; using existing configuration")
        for resource, origin in installation.get("provenance", {}).items():
            self.ok("resource provenance: " + resource, origin)
        for conflict in installation.get("diagnostics", []):
            self.warn("resource conflict: " + conflict["resource"], "legacy_config wins over installation profile")
        return True

    def get(self, dotted: str, default: Any = None) -> Any:
        current: Any = self.config
        for key in dotted.split("."):
            if not isinstance(current, dict):
                return default
            current = current.get(key, default)
        return current

    def path(self, value: object, *, base: Path | None = None) -> Path | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        if os.name != "nt" and (PureWindowsPath(raw).drive or raw.startswith("\\\\")):
            raise ValueError("Windows-host resource cannot be validated on Linux")
        path = Path(raw).expanduser()
        return (path if path.is_absolute() else (base or self.paths.runtime_root) / path).resolve()

    def resource(self, name: str, value: object, kind: str = "file", *, command: bool = False,
                 base: Path | None = None) -> Path | None:
        raw = str(value or "").strip()
        # Only explicitly selected bare commands may resolve via PATH; no fallback.
        if command and raw and "/" not in raw and "\\" not in raw:
            found = shutil.which(raw)
            if not found:
                self.fail(name, f"selected command not found: {raw}")
                return None
            raw = found
        try:
            path = self.path(raw, base=base)
        except ValueError:
            self.fail(name, "foreign-platform path; validate on its host, not relative to this checkout")
            return None
        valid = path is not None and (path.is_dir() if kind == "directory" else path.is_file())
        if kind == "executable":
            valid = valid and os.access(path, os.X_OK)
        if valid:
            self.ok(name, f"{path} ({kind} present; not executed/loaded)")
            return path
        self.fail(name, f"missing or invalid {kind}: {path or 'not configured'}", "Configure the selected integration resource; no fallback was used.")
        return None

    def setups(self, raw: dict[str, Any]) -> None:
        for key in ("ros_setup_paths", "extra_setup_paths"):
            values = raw.get(key) or []
            if not isinstance(values, (list, tuple)):
                values = [values]
            for index, value in enumerate(values):
                self.resource(f"{key}[{index}] ROS prefix", value)
        self.warn("ROS compatibility", "setup files inspected only; not sourced; built-prefix/ABI compatibility unverified")

    def check_utm(self) -> None:
        raw = self.get("devices.devices.utm_vision_runtime", {})
        workspace = self.resource("UTM workspace", raw.get("workspace_root"), "directory")
        script = raw.get("script_path") or (workspace / "scripts/start_utm_vision_stack.sh" if workspace else "")
        self.resource("UTM launch script", script, base=workspace)
        # UTM exports this value to a child launched with workspace_root as cwd.
        self.resource("UTM YOLO model", raw.get("environment", {}).get("YOLO_MODEL_PATH"), base=workspace)
        self.setups(raw)

    def check_realsense(self) -> None:
        raw = self.get("devices.devices.specimen_pose_tracker", {})
        self.resource("RealSense Python binding directory", raw.get("rsusb_pythonpath"), "directory")
        self.resource("RealSense native library directory", raw.get("rsusb_library_path"), "directory")
        self.setups(raw)
        self.warn("RealSense SDK", "native binding ABI and camera readiness unverified; SDK not imported")

    def check_lerobot(self) -> None:
        raw = self.get("lerobot.lerobot", {})
        self.resource("LeRobot source", raw.get("source_root"), "directory")
        self.resource("LeRobot conda", raw.get("conda_executable"), "executable", command=True)
        if not raw.get("conda_env_name"):
            self.fail("LeRobot environment", "conda_env_name not configured")
        else:
            self.warn("LeRobot environment", f"selected={raw['conda_env_name']}; existence/dependencies unverified; conda not executed")

    def check_slicer(self, kind: str) -> None:
        bambu = kind == "bambu"
        label = "Bambu Studio" if bambu else "PrusaSlicer"
        wrapper = self.paths.runtime_root / ("install/bambustudio/bambu-studio-wrapper" if bambu else "install/prusaslicer/prusa-slicer-docker")
        (self.ok if wrapper.is_file() and os.access(wrapper, os.X_OK) else self.warn)(
            "Bambu wrapper" if bambu else "PrusaSlicer wrapper", f"{wrapper}; wrapper availability is not application readiness")
        raw = self.get("devices.devices.printer." + ("bambu.slicer" if bambu else "slicer"), {})
        env_name = str(raw.get("executable_env") or ("BAMBU_STUDIO_EXECUTABLE" if bambu else "PRUSA_SLICER_EXECUTABLE"))
        env_value = os.environ.get(env_name, "").strip()
        selected = env_value or raw.get("executable_path")
        self.ok(label + " selection", "env:" + env_name if env_value else "resolved configuration")
        # Legacy slicer configuration is repository-relative in both consumers;
        # profile values already arrive absolute. Only Prusa's env override is
        # passed as a bare executable command directly to subprocess by runtime.
        path = self.resource(label + " executable", selected, "executable",
                             command=bool(env_value) and not bambu,
                             base=self.paths.repository_root)
        if path and path == wrapper.resolve():
            self.fail(label + " executable", "selected wrapper only; underlying application/container image is unverified",
                      "Select an installed application executable explicitly. Doctor does not execute wrappers or query Docker/Flatpak.")

    def check_isaac(self) -> None:
        raw = self.get("lerobot.lerobot", {})
        self.resource("Isaac Lab", raw.get("isaac_lab_path"), "directory")
        self.resource("Isaac Python", raw.get("isaac_sim_python"), "executable")
        self.resource("Isaac scene", raw.get("isaac_scene_path"))
        self.warn("Isaac compatibility", "GPU, simulator, model and environment compatibility unverified; not started")

    def check_desktop(self) -> None:
        for name in ("pyautogui", "Xlib"):
            (self.ok if PathFinder.find_spec(name) else self.fail)("desktop package: " + name, "package spec inspection only; not imported")
        for name in ("scrot", "wmctrl", "xdotool"):
            self.resource("desktop tool: " + name, name, "executable", command=True)

    def check_endpoints(self) -> None:
        """Report URL references, never secrets or whole configuration blobs."""
        def walk(value: Any, prefix: str = "") -> None:
            if not isinstance(value, dict):
                return
            for key, item in value.items():
                if not isinstance(key, str):
                    continue
                label = f"{prefix}.{key}" if prefix else key
                if _SECRET_KEY.search(key):
                    continue
                if isinstance(item, dict):
                    walk(item, label)
                elif isinstance(item, str):
                    selected = os.environ.get(item, "") if key.endswith("_env") else item
                    if "://" in selected and ("url" in key.lower() or "endpoint" in key.lower()):
                        self.ok("endpoint: " + label, selected + " (not contacted)")
        walk(self.config)

    def check_hardware(self) -> None:
        """Legacy explicit opt-in only. Never invoked by default or --core-only."""
        self.category = "hardware"
        self.warn("hardware scope", "explicit enumeration requested; outside offline installation acceptance")
        try:
            rs = importlib.import_module("pyrealsense2")
            devices = list(rs.context().query_devices())
            self.ok("RealSense hardware", f"visible devices={len(devices)}; not hardware acceptance")
        except Exception as exc:
            self.warn("RealSense hardware", f"{type(exc).__name__}: enumeration unavailable; error text suppressed")

    def run(self) -> list[dict[str, str]]:
        self.results = []
        self.category = "core"
        for check in (self.check_core_files, self.check_python, self.check_imports,
                      self.check_source_origins, self.check_cli, self.check_secrets_policy):
            try:
                check()
            except (OSError, ValueError) as exc:
                self.fail(check.__name__, f"{type(exc).__name__}: local inspection failed; error text suppressed")
        loaded = self.load_config()
        self.add("warn", "LLM readiness",
                 "Not verified by offline installation checks; model services and API authorization are separate.",
                 "Enable the intended API route or load the configured local models, then verify an actual response before experiments.",
                 status="unverified")
        if loaded:
            try:
                self.check_endpoints()
            except Exception as exc:
                self.fail("endpoints", f"{type(exc).__name__}: endpoint inspection failed; error text suppressed")
        for integration in INTEGRATIONS:
            if integration == "slicer":
                continue
            self.category = integration if integration in self.integrations else "optional"
            if integration not in self.integrations:
                self.add("info", integration, "not selected; not configured for this diagnostic run; resources not inspected", status="not_selected")
            elif loaded:
                try:
                    if integration in ("bambu", "prusa"):
                        self.check_slicer(integration)
                    else:
                        getattr(self, "check_" + integration)()
                except (OSError, ValueError, TypeError, AttributeError) as exc:
                    self.fail(integration, f"{type(exc).__name__}: invalid resource configuration; error text suppressed")
        if self.hardware:
            self.check_hardware()
        return self.results

    def exit_code(self) -> int:
        return int(any(item["level"] == "fail" for item in self.results))


def render_text(results: list[dict[str, str]]) -> None:
    for item in results:
        print(f"[{item['level'].upper()}] [{item.get('category', 'core')}] {item['name']}: {item['detail']}")
        if item.get("hint"):
            print(f"       hint: {item['hint']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print the compatible ok/results JSON object.")
    parser.add_argument("--core-only", action="store_true", help="Offline core inspection only.")
    parser.add_argument("--integration", action="append", choices=INTEGRATIONS, default=[],
                        help="Require local integration resources; repeatable; no tools executed.")
    parser.add_argument("--hardware", action="store_true", help="Explicit RealSense enumeration; outside offline acceptance.")
    args = parser.parse_args()
    if args.core_only and (args.integration or args.hardware):
        parser.error("--core-only cannot be combined with --integration or --hardware")
    try:
        doctor = Doctor(core_only=args.core_only, hardware=args.hardware, integrations=args.integration)
        results = doctor.run()
        code = doctor.exit_code()
    except (OSError, ValueError) as exc:
        results = [{"level": "fail", "name": "runtime paths", "category": "core", "status": "fail",
                    "detail": f"{type(exc).__name__}: path configuration invalid; source text suppressed", "hint": "Check repository layout and explicit path bindings."}]
        code = 1
    if args.json:
        print(json.dumps({"ok": code == 0, "results": results}, ensure_ascii=False, indent=2))
    else:
        render_text(results)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
