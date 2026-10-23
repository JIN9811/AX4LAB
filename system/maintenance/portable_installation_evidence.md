<!-- atr-doc
doc_type: evidence
subtype: test_report
status: active
authority: evidentiary
audience: [maintainer, developer, operator]
scope: [installation, portability, isolated_verification]
summary: Linux source relocation, offline core install, launcher and contract evidence with explicit acceptance gaps.
related_docs:
  - system/specs/2026-10-23-portable-installation-design.md
  - runtime/install/README.md
supersedes: []
-->

# Portable installation evidence — 2026-10-23

This is software evidence, not hardware commissioning or universal Linux support.
Baseline: `75c61d5`; installation implementation before integration repair:
`9fb5ae8`. Task 5 also restores existing explicit relative script semantics:
pose overrides remain repository-relative, UTM overrides remain external-workspace-
relative. Only absent code-owned defaults use the runtime root. Profile resource
paths are already absolute; ROS setup paths remain runtime-relative. Doctor uses
the same UTM script base. No experiment algorithm, order, prompt, threshold,
device command, module/package identity or Runtime IDE route was changed.

## Environment and isolation

- Ubuntu 24.04.4 LTS, aarch64, CPython 3.12.3, uv 0.11.23.
- Frozen core: 103 installed packages; Torch 2.12.1, BoTorch 0.18.1,
  GPyTorch 1.15.2. A CPU GP posterior was finite; GPU execution was not tested.
- Validation environment: frozen core + dev, 121 packages, pytest 9.1.1,
  build 1.5.0, setuptools 81.0.0. It is not the relocated application's Python.
- Test-only OpenCV headless 5.0.0.93 was exposed read-only from an already prepared
  scratch environment for the existing pose-tracker tests. It was not added to
  core or installed in the relocated environment.
- Archive checks additionally exposed only Ubuntu's wheel 0.42.0 package and
  metadata read-only. Core + dev alone did not supply this build-system requirement.
  This test-only build tool is not evidence of a frozen standalone distribution
  build environment and was absent from relocation/launcher checks.
- All application/test execution used `bwrap --unshare-all --cap-drop ALL`, private
  PID/network/mount/IPC/user namespaces, synthetic `/dev`, fresh HOME and `/tmp`,
  read-only `/usr`, no host home, original source, credentials or editable source.
  Only CPU `possible` and `present` files were exposed for ordinary numeric tests;
  strict namespace-fixture runs omitted all `/sys`. No GPU/camera/serial devices,
  host services, model endpoints or network downloads were available.
- Node 22.22.2/npm 10.9.7; tracked frontend lock installed with
  `npm ci --ignore-scripts --no-audit --no-fund` in the clone-local environment.
  No frontend code changed in Task 5.

## Source relocation and actual launch

Export tracked source only (Git archive modes should be normalized with
`git -c tar.umask=0022 archive HEAD`); never copy `.venv`, private stores or `.git`.
The exported source was mounted at `/relocated/AX4LAB moved source`, with
HOME `/tmp/new-user` and caller cwd `/tmp/unrelated`. The tests assert all five
namespaces differ from the host, zero effective capabilities, absence of
the operator's host home and hardware device nodes. This denies the original paths by mount
boundary, not just by a convention to avoid using them.

The real bootstrap created a NEW `.venv` using the existing downloaded wheel
cache, offline, with no source build or editable project install. Its environment:

```text
UV_BIN=/uv
UV_OFFLINE=1
UV_NO_BUILD=1
UV_LINK_MODE=hardlink
PYTHON_BIN=/usr/bin/python3
```

The bootstrap itself sets checkout-local `UV_PROJECT_ENVIRONMENT` and
`UV_CACHE_DIR`, checks `uv lock --check`, then calls `uv sync --frozen
--no-default-groups --no-install-project`. Hardlinking cached wheel files into a
new environment is not copying an old installed environment. A second sandbox
REMOVED both uv and its cache mount before running application checks.

Exact invocation pattern (absolute `export`, `validation`, `cache`, `uv` refer
only to the prepared scratch artifacts; `phase` is `bootstrap` then `runtime`):

```bash
mounts=()
selection='not bootstrap'
if [ "$phase" = bootstrap ]; then
  mkdir -p "$export/.cache/uv"
  mounts=(--bind "$cache" '/relocated/AX4LAB moved source/.cache/uv' --ro-bind "$uv" /uv)
  selection=bootstrap
fi
namespaces='{'
for name in pid net mnt ipc user; do
  namespaces+="\"$name\":\"$(readlink /proc/self/ns/$name)\","
done
namespaces="${namespaces%,}}"
env -i PATH=/usr/bin:/bin bwrap --unshare-all --die-with-parent --new-session --cap-drop ALL \
  --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
  --proc /proc --dev /dev --tmpfs /tmp --dir /tmp/new-user --dir /tmp/unrelated \
  --ro-bind /sys/devices/system/cpu/possible /sys/devices/system/cpu/possible \
  --ro-bind /sys/devices/system/cpu/present /sys/devices/system/cpu/present \
  --bind "$export" '/relocated/AX4LAB moved source' --ro-bind "$validation" /validation \
  "${mounts[@]}" --clearenv --setenv PATH /usr/bin:/bin --setenv HOME /tmp/new-user \
  --setenv PYTHONDONTWRITEBYTECODE 1 --setenv PYTHONNOUSERSITE 1 \
  --setenv ATR_PORTABLE_CHECKOUT '/relocated/AX4LAB moved source' \
  --setenv ATR_PORTABLE_HOST_NAMESPACES "$namespaces" --chdir /tmp/unrelated -- \
  /validation/bin/python -m pytest \
  '/relocated/AX4LAB moved source/runtime/tests/integration/test_portable_installation.py' \
  -vv --tb=short -k "$selection"
```

Results: bootstrap **1 passed**, runtime **4 passed** (final 6.45 seconds).
The ordinary full suite skips these five tests without the explicit opt-in.
Their actual boundaries are:

- `test_bootstrap_creates_fresh_core_without_global_launcher`: dry-run has no
  environment/.env writes; actual offline bootstrap and real core doctor succeed;
  no global `atr` or shell-rc file is installed.
- `test_relocated_python_config_and_writes_belong_to_new_checkout`: source `app`
  and config loader origins are in the relocated runtime; FastAPI/Torch/BoTorch/
  GPyTorch origins and Python prefix are in its new `.venv`; profile-relative
  model paths resolve against the external profile; output is in its selected store.
- `test_doctor_uses_selected_profile_without_starting_integrations`: core-only
  succeeds; explicitly selected missing UTM resources fail without creating them.
- `test_launcher_refuses_stale_environment_before_server_start`: an old prefix
  marker is rejected before launch; the test restores the marker.
- `test_actual_local_launcher_serves_idle_gui_and_test_profiles`: actual
  `run_local.sh → app.serve → app.main`, no fixture-server alternative. Relative
  profile selection survives an unrelated cwd; contaminating PYTHONHOME/PYTHONPATH
  are cleared. GET `/api/state`, `/`, `/live`, `/ide`, and
  `/api/test-mode-execution-profiles` return successfully. State remains test/idle,
  zero loops; log paths stay under the relocated run store. Only private loopback
  HTTP is used. No POST, connect request, model load or experiment is triggered.

The last test was mutation-checked: removing `normalize_installation_profile`
from the exported launcher made it fail with `FileNotFoundError` before startup
(1 failed, 4 deselected). Restoring the real launcher returned all four checks to
green. No mutation was made to the working production launcher.

## Baseline comparisons and integration repair

Exact focused selection, executed for BOTH baseline and current exports:

```text
tests/unit/test_package_contracts.py
tests/unit/test_langgraph_runtime.py
tests/unit/test_module_control_views.py
tests/unit/test_runtime_reference_roots.py
tests/unit/test_orchestrator_capabilities.py
tests/unit/test_ide_module_lifecycle_js.py
tests/integration/test_agent_execution_graph_api.py
tests/integration/test_packages_api.py
tests/integration/test_design_module_lifecycle.py
tests/unit/test_runtime_paths.py
tests/unit/test_runtime_path_consumers.py
tests/unit/test_runtime_bridge_roots.py
tests/unit/test_runtime_printer_roots.py
tests/unit/test_runtime_lerobot_roots.py
tests/unit/test_runtime_app_bridge_roots.py
tests/unit/test_runtime_knowledge_roots.py
tests/unit/test_runtime_app_knowledge_roots.py
tests/unit/test_runtime_ancillary_roots.py
tests/integration/test_orchestrator_setup_loop.py
```

The strict comparison envelope uses the same namespace/read-only `/usr`/synthetic
`/dev` boundary above, exports at `/snapshot`, validation Python at `/validation`,
scratch OpenCV at `/test-only`, Node at `/node`, no `/sys`, and these settings:

```text
PATH=/:/usr/bin:/bin
HOME=/tmp/new-user
PYTHONPATH=/snapshot/runtime:/test-only:/validation/lib/python3.12/site-packages
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
ATR_SANDBOX_HOST_NAMESPACES=<same host namespace JSON as above>
ATR_SANDBOX_HOST_PID=<shell PID> ATR_SANDBOX_HOST_PATH=<clone cwd>
ATR_VALIDATION_PYTHON=/validation/bin/python
AUTONOMOUS_USE_REAL_LLM_IN_TEST=0 AUTONOMOUS_ALLOW_MOCK_FALLBACK=1
AUTONOMOUS_BACKEND=ollama OLLAMA_BASE_URL=http://127.0.0.1:9
NEMOCLAW_AUTO_START_PROXY=0
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
ATR_CPU_WORKERS=1 MPLBACKEND=Agg
cwd=/snapshot/runtime
command=timeout 300 /validation/bin/python -m pytest <selection above> -q --tb=short
```

Final baseline and current: **411 passed, 6 failed, 71 warnings** each
(51.43 and 51.29 seconds). The six unchanged failures are:

1. `tests/integration/test_packages_api.py::test_full_graph_package_roundtrip_is_detached_and_catalog_never_reads_private_memory`:
   catalog expectation still includes retired `cae`.
2. `tests/integration/test_orchestrator_setup_loop.py::test_confirmed_setup_enters_original_initial_lhs_and_real_design[design-virtual_bridge]`
3. Same test `[specimen-virtual_bridge]`.
4. Same test `[specimen-installed_printer]`.
5. Same test `[specimen-physical_print]`.
6. Same test `[next_design-virtual_bridge]`.
   All five fail setup validation with `Unsupported parameter or unit in
   parameter_space` (the existing fixture submits `relative_density`). No
   scientific checks, loop fixtures, thresholds or policies were weakened.

An initial envelope did not supply the repository-specific namespace attestation
or the validation site to a deliberate `python -S` child. That caused
`test_main_resources_use_finalized_unrelated_roots` to fail in both exports.
Correcting the envelope (not the production code or test) made it pass in both.

Initial current-vs-baseline comparison also caught 18 installation-related deltas:

- Three real regressions: `test_changed_mixed_bridge_arguments_keep_legacy_storage_base`,
  `test_pose_equipment_pinn_defaults_and_explicit_paths[custom/place]`, and
  `test_bound_utm_calibration_launch_keeps_external_workspace_and_argv`.
  Their original expectations were retained and the production path-base bug fixed.
- `test_shipped_omissions_preserve_flat_values_and_select_split_defaults` and
  three `test_lerobot_absent_defaults_and_explicit_bases` cases now assert absent
  external resources and explicit override preservation, not the old user's homes.
- `test_bound_pose_launch_preserves_command_env_and_script_parent` supplies real
  inert setup files now that missing ROS setup paths fail preflight.
- `test_lerobot_nested_source_and_direct_store_defaults` and
  `test_bound_e2e_command_keeps_all_existing_nonpath_arguments` supply an explicit
  inert Conda executable/environment and external Isaac paths; command argv is
  still asserted, with no executable actually run.
- `test_app_lazy_lerobot_uses_frozen_binding`, `test_e2e_helper_keeps_legacy_and_bound_config_sources`,
  `test_validate_cli_uses_bound_source_and_private_roots`, and
  `test_app_lazy_factories_retain_binding` now validate the loader's `paths=` argument.
- `test_smoke_cli_absent_root_binds_but_explicit_repository_stays_legacy[lerobot_isaac_lab_e2e_smoke]`
  and two `test_e2e_explicit_runtime_root_validates_before_import_path_or_fixture_work`
  matching-runtime cases complete their test double's `isaac_resource_defaults` interface.
- `test_doctor_separates_git_venv_and_environment_from_runtime_resources` now tests
  the offline metadata API, traps subprocesses, and verifies the actual prefix marker.

New `test_legacy_relative_utm_script_matches_external_workspace` failed before
the doctor base correction, then passed. The combined repair/profile/resource/
doctor/root command passed **182 tests** (one namespace-specific test deliberately
run in the strict comparison instead); warnings are existing FastAPI deprecations.

## Broad suites, distribution and remaining acceptance gaps

- Separately bounded exact mock-loop comparison (same numeric envelope and
  `timeout 300 /validation/bin/python -m pytest
  'tests/integration/test_controller_run.py::test_controller_completes_test_run[2]'
  -vv --tb=short`): current **1 passed, 59 warnings in 150.37 seconds**;
  baseline **1 passed, 59 warnings in 153.43 seconds**. The unchanged test runs
  the real controller/graph/agents with explicit virtual boundaries and checks
  run events, completed cycles and per-agent design/analysis/BO artifacts.
  Warnings are existing FastAPI/NumPy deprecations. This is not a physical loop.
- Full Python attempts: baseline timed out at 600 seconds (exit 124). A baseline
  collection attempt reported 6,439 items plus missing test-only `cv2`; this is not
  a core-install failure. Current collected **6,569**, then timed out at 600 seconds
  during `test_controller_completes_test_run[20]`; `[2]` passed. There was no complete
  pytest result or finished XML. The long CPU-bound geometry/loop work was not
  shortened or bypassed. Neither full suite is claimed green.
  The current command was `timeout 600 /validation/bin/python -m pytest -vv
  --tb=short -o faulthandler_timeout=120`, from `/work/runtime` in the isolated
  exported checkout (`PYTHONPATH=/work/runtime:/test-only`).
  Task 5 repair files were overlaid into that scratch snapshot near the end while
  the already-imported `[20]` test was running. This is incomplete, mutable-snapshot
  evidence, **not** a completed test of one immutable final revision. Completed
  focused, mock-loop, relocation and archive checks provide the final-code evidence.
  The original implementer recovered this complete historical wrapper from its
  tool-call context (not a rerun); `scratch` denotes the prepared validation
  artifacts and `tree` the disposable `current-suite` export, initially `9fb5ae8`:

  ```bash
  env -i PATH=/usr/bin:/bin bwrap \
    --unshare-all --die-with-parent --new-session --cap-drop ALL \
    --ro-bind /usr /usr --symlink usr/bin /bin \
    --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
    --proc /proc --dev /dev --tmpfs /tmp --dir /tmp/new-user --dir /tmp/unrelated \
    --ro-bind /sys/devices/system/cpu/possible /sys/devices/system/cpu/possible \
    --ro-bind /sys/devices/system/cpu/present /sys/devices/system/cpu/present \
    --bind "$tree" /work --ro-bind "$scratch/validation-venv" /validation \
    --ro-bind "$scratch/deps/lib/python3.12/site-packages/cv2" /test-only/cv2 \
    --ro-bind "$scratch/deps/lib/python3.12/site-packages/opencv_python_headless.libs" /test-only/opencv_python_headless.libs \
    --clearenv --setenv PATH /usr/bin:/bin --setenv HOME /tmp/new-user \
    --setenv PYTHONPATH /work/runtime:/test-only --setenv PYTHONNOUSERSITE 1 \
    --setenv PYTHONDONTWRITEBYTECODE 1 --setenv AUTONOMOUS_USE_REAL_LLM_IN_TEST 0 \
    --setenv AUTONOMOUS_ALLOW_MOCK_FALLBACK 1 --setenv AUTONOMOUS_BACKEND ollama \
    --setenv OLLAMA_BASE_URL http://127.0.0.1:9 --setenv NEMOCLAW_AUTO_START_PROXY 0 \
    --setenv OMP_NUM_THREADS 1 --setenv OPENBLAS_NUM_THREADS 1 --setenv MKL_NUM_THREADS 1 \
    --setenv NUMEXPR_NUM_THREADS 1 --setenv ATR_CPU_WORKERS 1 --setenv MPLBACKEND Agg \
    --chdir /work/runtime -- \
    timeout 600 /validation/bin/python -m pytest -vv --tb=short -o faulthandler_timeout=120
  ```

  This predates the `/snapshot`, namespace-attestation, Node and build-only mounts
  in the later focused envelope. `faulthandler_timeout=120` prints diagnostics;
  the outer 600-second timeout ended the run with exit 124.
- Frontend complete comparison: current **464 passed / 466**, baseline
  **463 passed / 465**. Identical two failures: `tests/js/live_initial_agent.test.cjs`
  “startup replaces restored DSN selection with ORC report without changing subsequent
  selections” (`2 !== 1`), and `tests/js/live_resources.test.cjs` “session refresh
  preserves host telemetry rather than replacing it with empty session data”
  (`window is not defined`). Command: `/node --test tests/js/*.cjs tests/js/*.js`
  under the same isolation, readonly installed Node dependencies and
  `ATR_VALIDATION_PYTHON=/deps/bin/python` pointing to fresh core. Earlier missing
  `three` failures were resolved solely by installing the tracked Node lock.
- Actual archive gate: `ATR_DISTRIBUTION_BUILD=1`, with the explicit build-only
  wheel path appended to PYTHONPATH, `/validation/bin/python -m pytest
  tests/unit/test_distribution_layout.py -q --tb=short`: **4 passed**. Builds
  wheel + sdist, checks exact allowlists/bytes/modes, and rejects injected private
  files. Initial attempts separately exposed missing wheel, stale copied doc hashes,
  and Git archive's 0664 export mode; these harness/build prerequisites were corrected,
  not hidden by relaxing the archive assertions.
- Documentation validator: `/validation/bin/python scripts/validate_documentation.py
  --root /snapshot`: passed. All **124 local file/anchor links** in the seven
  changed/new guides/evidence files resolve (repository reference parser used;
  remote websites were not fetched). Positive distribution selection and only the current
  identity overlay were refreshed; historical identity proofs were preserved.
- Final combined installation/resource/root/archive regression command: **172
  passed, 5 skipped, 21 warnings in 10.94 seconds**. The five opt-in relocation
  tests were run separately above; they intentionally skip without their sandbox
  environment. An earlier combined attempt caught the temporary link-check helper
  at the exported repository root (`test_executable_project_is_contained_under_runtime`);
  moving that scratch-only helper under runtime/tools restored the existing layout
  assertion without editing it. No helper was added to the tracked repository.
  The complete final selection, from `/snapshot/runtime` under the sandbox
  envelope below, was:

  ```bash
  env ATR_DISTRIBUTION_BUILD=1 \
    PYTHONPATH=/snapshot/runtime:/validation/lib/python3.12/site-packages:/build-only \
    /validation/bin/python -m pytest \
    tests/unit/test_distribution_layout.py tests/unit/test_portable_bootstrap.py \
    tests/unit/test_installation_manifest.py tests/unit/test_portable_doctor.py \
    tests/unit/test_portable_resource_defaults.py tests/unit/test_installation_profile.py \
    tests/unit/test_runtime_bridge_roots.py tests/unit/test_runtime_lerobot_roots.py \
    tests/unit/test_runtime_app_bridge_roots.py tests/unit/test_runtime_ancillary_roots.py \
    tests/integration/test_portable_installation.py -q --tb=short
  ```
- **Native Windows remains an unmet acceptance criterion.** No native Windows
  runner was available. Linux checks/PowerShell parsing do not establish native
  drive/UNC path, installer, exit-code or bridge startup correctness. Windows
  wheelhouse/transitive freezing remains separately deferred.
- ROS builds/prefix/ABI, GPU drivers and execution, external Conda/LeRobot contents,
  model licenses/identity, calibration/device matches and all real hardware remain
  unverified. Offline doctor is not a hardware-readiness certificate. No service
  cutover, global alias replacement, private-state migration, push or publication
  was performed.

## Reproducible focused-test sandbox envelope

This is the durable equivalent of the local `run-sandbox.sh` used for final scoped
checks. Set `export` to a disposable tracked-source export (644/755 tracked modes),
`validation` to the prepared core+dev virtualenv, `opencv_site` to the prepared
test-only OpenCV site-packages, and `node` to the Node executable. These are scratch
artifacts, not an operating environment or original checkout. Supply the complete
command above as the arguments to `sandbox`. The original broad current run used
`/work` rather than `/snapshot`; its exact pytest invocation is recorded above.
No expensive broad run was repeated to reconstruct this record.

```bash
sandbox() {
  local namespaces='{' name
  for name in pid net mnt ipc user; do
    namespaces+="\"$name\":\"$(readlink /proc/self/ns/$name)\","
  done
  namespaces="${namespaces%,}}"
  env -i PATH=/usr/bin:/bin bwrap --unshare-all --die-with-parent --new-session --cap-drop ALL \
    --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
    --proc /proc --dev /dev --tmpfs /tmp --dir /tmp/new-user --dir /tmp/unrelated \
    --ro-bind /sys/devices/system/cpu/possible /sys/devices/system/cpu/possible \
    --ro-bind /sys/devices/system/cpu/present /sys/devices/system/cpu/present \
    --bind "$export" /snapshot --ro-bind "$validation" /validation --ro-bind "$node" /node \
    --ro-bind "$opencv_site/cv2" /test-only/cv2 \
    --ro-bind "$opencv_site/opencv_python_headless.libs" /test-only/opencv_python_headless.libs \
    --ro-bind /usr/lib/python3/dist-packages/wheel /build-only/wheel \
    --ro-bind /usr/lib/python3/dist-packages/wheel-0.42.0.dist-info /build-only/wheel-0.42.0.dist-info \
    --clearenv --setenv PATH /:/usr/bin:/bin --setenv HOME /tmp/new-user \
    --setenv ATR_VALIDATION_PYTHON /validation/bin/python \
    --setenv ATR_SANDBOX_HOST_NAMESPACES "$namespaces" \
    --setenv ATR_SANDBOX_HOST_PID "$$" --setenv ATR_SANDBOX_HOST_PATH "$PWD" \
    --setenv PYTHONPATH /snapshot/runtime:/test-only:/validation/lib/python3.12/site-packages \
    --setenv PYTHONNOUSERSITE 1 --setenv PYTHONDONTWRITEBYTECODE 1 \
    --setenv AUTONOMOUS_USE_REAL_LLM_IN_TEST 0 --setenv AUTONOMOUS_ALLOW_MOCK_FALLBACK 1 \
    --setenv AUTONOMOUS_BACKEND ollama --setenv OLLAMA_BASE_URL http://127.0.0.1:9 \
    --setenv NEMOCLAW_AUTO_START_PROXY 0 --setenv OMP_NUM_THREADS 1 \
    --setenv OPENBLAS_NUM_THREADS 1 --setenv MKL_NUM_THREADS 1 --setenv NUMEXPR_NUM_THREADS 1 \
    --setenv ATR_CPU_WORKERS 1 --setenv MPLBACKEND Agg \
    --chdir /snapshot/runtime -- "$@"
}
```

For the strict namespace-specific comparison omit both CPU `/sys` mounts. The
build-only wheel package/metadata mounts and `/build-only` Python path are necessary
only for archive construction. They are not core installation dependencies and
were absent from the actual relocation/bootstrap/runtime envelope. No host HOME,
credentials, real devices, operating caches, or network are exposed by this envelope.

## Final bounded portability corrections

Starting from `286cc10`, the six final-review items were addressed together:

- Executable profile bindings retain lexical absolute paths through LeRobot
  configuration, required resources, Conda command selection, E2E CLI and synthetic
  worker values. A profile → loader → config → command test uses virtualenv-style
  Python symlinks plus `pyvenv.cfg`, executes only an inert `sys.prefix` probe, and
  confirms the selected environment survives; legacy and request overrides still win.
- Both RTC selectors become absolute after the final launch overrides are merged.
  Their compatibility base is the original child cwd: runtime for rollout, explicit
  lab/job cwd for those existing runners. Parent cwd is not substituted. Final
  POSIX child HOME also governs `~/` overrides. Tests execute only an inert JSON
  reporting child; external Isaac runners are intercepted before execution.
- Doctor skips non-string YAML endpoint keys and converts unexpected endpoint
  traversal exceptions into a redacted failure inside its JSON envelope. CLI-entry
  tests retain non-actuation tripwires and credential/query suppression.
- Profile-selector `~` expansion uses the public API's supplied HOME/USERPROFILE,
  tested with a different process HOME and without globally monkeypatching it.
- Correct `.atr-prefix` plus wrong interpreter `sys.prefix` is tested for both
  launcher and repeated setup, stopping before app/uv/environment mutation. Removing
  only the guard in the disposable export makes both tests fail; production guard
  code was unchanged. The separate requested-interpreter-change test remains.
- The full historical broad invocation, mutable-snapshot qualification, final
  scoped selection and build-only prerequisites are now durable above. Historical
  identity records were not rewritten; only the current-source overlay changed.
  Existing files suffice, so no distribution allowlist additions were necessary.

Focused RED against the pre-fix export: **11 failed, 2 passed, 101 deselected**
(the two already-correct prefix cases passed). Additional explicit lab/job-cwd
boundary RED: **2 failed, 1 passed, 27 deselected**, with five existing warnings.
Export-only prefix-guard/slicer-alias mutation RED: **4 failed, 42 deselected**.
The child-HOME regression was **1 failed, 43 deselected**, then **1 passed,
43 deselected** after correction. The initial RTC fixture lacked reproducible
layout metadata; it was corrected to use the legacy constructor before recording
the intended relative-handoff RED. No failed check was counted as successful.

Final GREEN used the **complete final selection printed above**, unchanged,
including actual archive builds and identity checks: **192 passed, 5 skipped,
21 warnings in 20.24 seconds**. These are focused checks, not a full-suite claim.
The five opt-in relocation checks were not repeated in this fix wave; their prior
actual acceptance remains separately recorded. Warnings are existing Pydantic
field-shadowing and FastAPI lifecycle deprecations. Native Windows, full-suite,
known baseline-failure, GPU/model and hardware limits remain exactly as disclosed
above. No original/Rebot installation, service, global launcher, private state,
device, model, network, publication or push action occurred.

Local raw evidence is retained under `.superpowers/sdd/2026-10-23-portable-installation/`:
`portable-bootstrap.log`, `portable-runtime-final.log`, `portable-mutation-red.log`,
`legacy-script-red.log`, `repair-green.log`, `contracts-*-corrected.log`,
`baseline-python.log`, `current-python.log`, `distribution-build-final.log`,
`documentation-validation.log`, `node-tests-current-complete-env.log`, and
`node-tests-baseline-complete-env.log`, `mock-loop-*.log`, `links.log`.
`final-scoped-corrected.log` records the final combined regression result.
These scratch logs are not published;
the commands, named failures, outcomes and limits above are the durable record.
