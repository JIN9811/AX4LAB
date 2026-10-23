# Portable Installation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Install and launch an isolated AX4LAB checkout without personal source paths or implicit reuse of the operating installation.

**Architecture:** Extend RuntimePaths and the existing configuration loading boundary with a narrow external-resource profile. Reuse bootstrap scripts and doctor, introduce a checkout-local launcher, and verify relocation without access to the original environment.

**Tech Stack:** Python 3.11+, JSON/YAML, Bash, PowerShell, existing uv lock and pytest/Node test infrastructure.

**Spec:** `system/specs/2026-10-23-portable-installation-design.md`

## Global Constraints

- Target Linux main PC and Windows UTM bridge; do not promise native Windows support for the whole Linux runtime.
- Work only in the AX4LAB clone; no original checkout, services, equipment, global launcher or Rebot workspace modifications.
- Preserve experiment logic, module/package identities, Runtime IDE contracts and private-store ownership.
- Do not move or automatically reuse calibration, datasets, policies or credentials.
- Setup and diagnostics never launch devices, models or experiments.
- Unavailable architecture, Windows or hardware verification remains an explicit acceptance gap.

## Review Focus

- A process started in a different directory must resolve the same profile and resources (tasks 1, 2, 3).
- A stale editable package or global launcher must not silently run the old checkout (tasks 3, 4, 5).
- Explicit user overrides must remain authoritative; unknown profile keys must not become experiment-setting overrides (task 1).
- A filtered worker environment must receive the same installation profile as its parent (tasks 1, 5).
- Missing optional equipment must not prevent GUI use; missing selected resources must not silently fall back (tasks 2, 4).

## Task 1: External resource profile and shared configuration boundary

**Files:**
- Create `runtime/utils/installation_profile.py` and `runtime/configs/installation.example.json`.
- Modify `runtime/utils/config_loader.py`, `runtime/utils/runtime_process.py`, `.gitignore`.
- Create `runtime/tests/unit/test_installation_profile.py`.

**Interfaces:**
- `load_installation_profile(paths: RuntimePaths, *, environ: Mapping[str, str] | None = None) -> InstallationProfile`: immutable validated resources with source/provenance.
- `apply_installation_profile(bundle: dict, profile: InstallationProfile) -> dict`: copy-on-write application of allowlisted external-resource fields only.
- `installation_metadata(profile: InstallationProfile) -> dict[str, str]`: absolute profile selector for fresh processes; empty for unconfigured installations.
- Selector: `ATR_INSTALL_PROFILE`; default: `<repository_root>/installation.local.json`; schema: `atr.installation.v1`.
- Profile contains `schema` and `resources`. Resources are typed per integration, never arbitrary nested configuration patches. Initially cover UTM workspace/script/ROS setups/YOLO model, RealSense native binding path/ROS setups, LeRobot environment/source/cache paths, slicer executable and Isaac tool/scene paths. Add other audited external resources through the same reviewed allowlist.
- Explicit call/request/environment overrides retain existing precedence. Legacy configured resource fields remain valid; profile conflicts receive diagnostics rather than silently replacing explicit legacy values. Replace tracked personal defaults with portable defaults so profile selection is unambiguous.

- [ ] Write tests for absent optional profile, missing explicit profile, malformed schema, unknown key, relative paths with spaces, home expansion, foreign-platform paths, unresolved placeholders, and nonmutation of cached YAML.
- [ ] Assert rejected keys cannot change `mode`, thresholds, commands, robot identity or completion policy; assert existing explicit overrides win.
- [ ] Run `python -m pytest tests/unit/test_installation_profile.py -q` from runtime and observe expected failures.
- [ ] Implement validation/resolution and integrate the bundle loader; inventory direct YAML readers and update application consumers to use the shared result rather than parallel profile parsing.
- [ ] Add a fresh-subprocess test with a filtered environment; parent and child must report the same profile and source roots from an unrelated cwd.
- [ ] Run new tests plus runtime-path/configuration regressions; commit only this boundary and its tests.

## Task 2: Remove active personal defaults and fix subprocess paths

**Files:**
- Modify `runtime/configs/devices.yaml`, `runtime/configs/lerobot.yaml`, relevant system/model configuration defaults.
- Modify `runtime/device_bridges/camera_vision/specimen_pose_tracker.py`, `utm_runtime_bridge.py`, `runtime/scripts/vision/run_specimen_pose_snapshot.sh`.
- Modify `runtime/web/static/lerobot.js`, affected Isaac scripts and configuration serializers.
- Extend `runtime/tests/unit/test_specimen_pose_tracker.py`, `test_utm_runtime_bridge.py`; create `test_portable_resource_defaults.py`.

**Interfaces:** Consume task 1 resolved configuration; subprocess arguments and environment contain absolute host-local resource paths. GUI defaults derive from backend-owned resource information, not a username or old repository name.

- [ ] Write a regression test proving `ros/install/setup.bash` resolves under runtime_root before the bridge launches the script, not under scripts/vision.
- [ ] Test required setup-file absence reports a configuration failure without spawning ROS; unused integrations remain unconfigured. Do not introduce a new experiment-loop stop or retry policy.
- [ ] Test the GUI's default scene resolves to this checkout's scene, and explicit scene/tool values remain unchanged.
- [ ] Observe failures, implement the fixes, then rerun existing specimen/UTM and frontend tests.
- [ ] Audit active paths across configs, scripts, deployment manifests and GUI code; classify host-standard paths versus personal paths. Document external mount requirements rather than pretending hostPath volumes travel with Git.
- [ ] Remove personal defaults in active Isaac utilities; retain historical examples only when clearly labeled and non-executable.
- [ ] Commit path fixes with regression evidence.

## Task 3: Checkout-local launch and reproducible setup

**Files:**
- Create `runtime/install/run_local.sh` and `runtime/tests/unit/test_portable_bootstrap.py`.
- Modify `runtime/install/bootstrap_linux.sh`, `install_cli.sh`, `bootstrap_windows.ps1` where shared setup behavior applies.
- Audit/update `runtime/pyproject.toml`, `uv.lock`, requirement exports and distribution allowlists as needed for frozen core installation.
- Extend existing Windows bridge installer tests for host-local path handling.

**Interfaces:** `run_local.sh` derives repository/runtime roots from itself, uses only the checkout `.venv`, and passes arguments to the existing server entrypoint. Core setup retains dry-run and adds explicit opt-in global CLI installation; no server startup is part of bootstrap.

- [ ] Write shell-subprocess tests with fake executables in a temporary checkout: spaces in paths, unrelated cwd, missing venv, stale venv prefix, another global atr, doctor failure, repeat setup and dry-run.
- [ ] Assert bootstrap does not install the global alias by default, and global installer refuses to replace a different binding without an explicit override even at the same target pathname.
- [ ] Observe failures, implement launcher/setup safeguards, and rerun the shell tests without invoking real pip/apt/devices.
- [ ] Check existing lock consistency and supported wheel availability in a disposable environment; use frozen dependency installation rather than unconstrained requirements resolution. Do not fabricate compatible GPU pins or install into the operating environment.
- [ ] Preserve legacy installation entry points; document explicit optional stacks. Record selected external revisions/model checksums through a sanitized installation manifest; absent/unverified values are not treated as reproducibility evidence.
- [ ] Keep Windows UTM installation on its existing bridge path. Test native PowerShell path quoting in Windows CI; do not claim Linux parser checks cover it.
- [ ] Commit installer and package-lock changes only after relevant tests.

## Task 4: Non-actuating readiness checks

**Files:**
- Modify `runtime/scripts/doctor.py`; create `runtime/tests/unit/test_portable_doctor.py`.

**Interfaces:** Preserve existing JSON `ok/results` shape and `--core-only`; add repeatable `--integration` selection for strict resource checks. Reuse task 1 configuration and provenance. Default diagnostics do not import `app.main` or initialize its runtime.

- [ ] Write tests trapping app bootstrap, device SDK enumeration, socket connections and process creation; default doctor must not invoke these. Isolate permitted local file/tool inspection explicitly.
- [ ] Test missing selected resources produce nonzero exit, unused integrations are reported separately, wrong checkout launchers/import origins are detected, and credentials/userinfo/query tokens are redacted.
- [ ] Test that a wrapper's existence alone does not prove Bambu Studio is installed; distinguish wrapper availability from selected executable readiness.
- [ ] Observe failures, implement checks and run the test suite. Keep explicit hardware enumeration outside default installation acceptance.
- [ ] Have bootstrap propagate core doctor failures instead of suppressing them; test the actual exit-status boundary.
- [ ] Commit doctor updates with tests.

## Task 5: Isolated relocation, contract regression and operator instructions

**Files:**
- Create `runtime/tests/integration/test_portable_installation.py`.
- Extend `runtime/tools/repository_layout/sandbox.py` only if needed for original-tree denial.
- Update `runtime/install/README.md`, `docs/project/REQUIREMENTS.md` and relevant existing English/Korean installation guides, without changing their overall structure.
- Add an evidence summary under `system/maintenance/` with exact commands, environments and remaining gaps.

**Interfaces:** Existing module/package/Runtime IDE contracts remain unchanged. Tests consume the task 1 profile and task 3 launcher/bootstrap rather than test-only alternative execution paths.

- [ ] Run path tests with a new HOME, unrelated cwd and copied checkout whose name contains spaces. Ensure original source/cache paths are unavailable, not merely unused by convention.
- [ ] Validate a fresh core environment, imported package origins, output locations and mock-only GUI/test-mode startup in a network/device-isolated sandbox. Do not run the physical loop.
- [ ] Compare configuration/contract and mock-loop behavior against the preimplementation clone, excluding intended resource/provenance differences.
- [ ] Run the repository's Python suite and relevant Node/frontend suites inside the isolation boundary; record all baseline and new failures by test name. Do not weaken experiment tests to make installation changes pass.
- [ ] Validate Windows bridge setup in an isolated Windows runner; if unavailable, record this as an unmet acceptance criterion.
- [ ] Document exact setup/profile/launch/check commands, external installation prerequisites, data/calibration import boundaries and rebuild requirements after moving installed environments.
- [ ] Verify links and publication hygiene, inspect the complete diff and obtain whole-branch code review. Commit verified changes locally; do not publish a new GitHub repository or switch operating services without the release step.

## Execution and reporting

The user approved subagent-driven implementation on 2026-10-23. Execute tasks sequentially with a fresh implementer and task-scoped independent review; finish with a whole-branch review.

Before every completion claim, distinguish implemented code, isolated software verification, Windows validation and actual hardware validation. No one-host result establishes support for every Linux architecture or GPU stack.
