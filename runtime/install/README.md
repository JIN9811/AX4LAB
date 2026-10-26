# Install

This folder contains setup notes and launchers for the local
`AX4LAB` checkout.

Source audit: 2026-09-29 against `dd0d772`; this review did not install software,
restart services, or commission hardware. Host-specific verification below is
retained evidence rather than a new test result.

Public product and distribution names are `AX4LAB` and `ax4lab`; the optional
terminal command is `ax4lab`, independent of the original project's `atr`.
Compatibility identifiers remain unchanged: `atr.*` schemas, `atr_closed_loop`,
internal module/file names, Windows `ATR` data directories, and low-level
`ATR_*`/`AUTONOMOUS_*` settings. Launcher controls use `AX4LAB_*` as described
below. Citation metadata and dated evidence retain their original identities.

## Source layout and existing deployments

Commands below that install the main environment run from the outer repository
root. Executable source, configuration and installers are under `runtime/`;
`.venv` and `.env` remain at the outer root. Direct Python module launches run
with `runtime/` as their working directory, using the activated outer environment.
Paths such as `configs/...` describe runtime-relative configuration; private
`memory`, run and artifact stores are selected through explicit RuntimePaths
bindings, not by the presence of a similarly named directory.

Do not bootstrap or restart an active installation to apply this layout change.
Follow the [stopped-maintenance cutover runbook](../../system/maintenance/repository_layout_cutover.md),
including the separate private-state approval and deployed ROS rebuild gates.

AX4LAB supports two inference modes:

- Local: select `vllm`, `ollama`, or `nemoclaw`, and unload the Main GUI API-key
  control. The selected local service must be running and its models loaded.
- API: load the saved key in the Main GUI. OpenAI becomes the first route, with
  the selected local backend as fallback. Select `openai` for API-only use.

The saved API-key enabled state takes precedence over the static fallback in
`configs/models.yaml`. A registered but unloaded key stays disabled after restart;
copying credentials does not activate inference.

## Recommended Fresh-Install Flow

Use this order on a new PC:

1. Clone the approved AX4LAB source repository.
2. Run the platform bootstrap for the host OS.
3. Run `doctor --core-only`, then `doctor --integration NAME` for only the
   equipment selected for this workstation. Default checks do not inspect unused integrations.
4. Install only the external runtimes needed for that workstation: local AI,
   Bambu/Prusa slicing, LeRobot/RealSense, Windows equipment bridge, or graph
   database.

Public source: [JIN9811/AX4LAB](https://github.com/JIN9811/AX4LAB).
Links to the original repository elsewhere retain their historical provenance.

Linux main-PC default (install Python 3.11+ and `uv` first):

```bash
git clone https://github.com/JIN9811/AX4LAB.git
cd AX4LAB
bash runtime/install/bootstrap_linux.sh --dry-run
bash runtime/install/bootstrap_linux.sh
.venv/bin/python runtime/scripts/doctor.py --core-only
bash runtime/install/run_local.sh
```

Windows UTM bridge setup path (native execution remains unvalidated here):

```powershell
git clone https://github.com/JIN9811/AX4LAB.git
cd AX4LAB
powershell -ExecutionPolicy Bypass -File .\runtime\install\bootstrap_windows.ps1 -DryRun
powershell -ExecutionPolicy Bypass -File .\runtime\install\bootstrap_windows.ps1
# Dependencies only; start the bridge separately after configuring this Windows PC.
```

Windows limitations:

- The portable main-runtime setup targets Linux. This legacy Windows bootstrap
  entry point now delegates only to the existing Windows UTM/PyAutoGUI bridge
  installer with `-SetupOnly`. It does not install or certify the full runtime.
- Pass `-DataRoot 'C:\\path with spaces\\bridge data'` and, if needed,
  `-PythonLauncher 'C:\\Python311\\python.exe'`. Linux paths and drive-relative
  paths are rejected on the Windows host. `-DryRun` writes nothing.
- Setup-only installs bridge Python dependencies, but creates no scheduled task,
  shortcut, firewall rule, persistent user setting, or server process. The legacy
  bridge deployment installer remains available separately for those opt-ins.
- LeRobot live hardware, RealSense RSUSB, local NemoClaw/vLLM, Dockerized
  slicers, and Linux device permissions require WSL/Linux or separate
  conda/toolchain setup.
- Hardware memory files such as `memory/bambu_connection.json`,
  `memory/prusa_connection.json`, and `memory/lerobot_device_ports.json` are
  intentionally not copied through Git. Recreate them from the GUI on each PC.

### Frozen Linux core and optional stacks

Install `uv` separately; bootstrap never installs a package manager implicitly.
It runs `uv lock --check` before `uv sync --frozen --no-install-project`, targeting
only the outer checkout `.venv` and `.cache/uv`. `runtime/uv.lock` is authoritative;
`runtime/requirements.txt` is a generated, hash-bearing core-only export, not an
independently maintained dependency list. To refresh it after a reviewed lock
update, run from the repository root:

```bash
uv export --frozen --project runtime --no-dev --no-emit-project --output-file runtime/requirements.txt
```

The source launcher imports this checkout from `runtime/`; setup does not build
or install an editable/wheel distribution. Core includes the Mitsubishi PLC
client (`pymcprotocol`) in the server environment and BoTorch/GPyTorch/Torch
for Bayesian optimization. No separate PLC Conda environment is required.
`doctor --core-only` checks that the PLC package is present without importing it
or contacting a PLC; this is not a hardware connection test.
The locked PyPI Torch build can download
several GB of CUDA dependencies even for CPU use; GPU compatibility is not implied.
Python 3.11+ is declared by the project; actual platform acceptance must be recorded
separately. Native/hardware compatibility is not established by lock resolution.

`--with-piper` selects the `tts` extra only (no voice download or synthesis),
`--with-local-pyautogui` selects `desktop`, and `--with-realsense` selects `realsense`.
`--with-plc` and the `plc` extra remain compatible with older setup commands,
but PLC dependencies are now installed even without that flag.
The optional extras are locked but not certified on every
architecture. Each setup sync selects exactly the requested extras; repeat their
flags on subsequent setup runs to retain them. `--with-system-packages` separately
opts into apt network/system changes for X11 tools. Development and graph extras
remain explicit. ROS, LeRobot, Isaac, model servers, slicers and models retain their
separate installation/licensing/authentication procedures; no versions or GPU
combinations are claimed tested merely because a resource path exists.

`--dry-run` prints without commands or writes. No setup path launches the server
or devices. `--install-cli` explicitly installs the optional `ax4lab` command; an
existing different binding (including at the same pathname) is refused unless
the operator sets `AX4LAB_FORCE_INSTALL=1`. Default setup installs no global
command. Neither path modifies the original project's `atr` command.
The commands below using `ax4lab` assume that opt-in; otherwise use the checkout
Python directly for doctor. Doctor failures propagate as setup failures.

Moved or unmarked `.venv` directories are rejected. `--rebuild-venv` preserves the
old environment under `.venv.backup.*/environment` and creates a new one; it does
not reuse old editable installations. Do not move ROS install trees; rebuild them
using the integration's own setup. Failed downloads can be retried without rebuild.

Select external resources in `installation.local.json`, or with
`ATR_INSTALL_PROFILE`; the shell entry points normalize a relative selector against
the caller's directory before changing directories. No credentials, calibration,
private data, or original-PC state are imported automatically. Setup writes a local
ignored `installation.manifest.local.json`: lock hash, selected source HEAD revisions
(working-tree dirty status explicitly unverified), selected YOLO model SHA256,
and a small package-version inventory. It never runs `git status` or repository
clean/filter-process commands while inspecting source metadata.
It excludes remote URLs, paths and secrets. Missing/unverified entries are **not**
reproducibility evidence; byte hashes do not prove upstream model identity/license.
Only profile-selected resources are inspected; legacy config overrides are not
certified by this receipt. Other models/environments require separate receipts.

Start with only the integrations you need; the example is a schema reference,
not a ready-to-run equipment profile:

```bash
cp runtime/configs/installation.example.json installation.local.json
# Edit installation.local.json: remove unused resource groups and set real paths.
ATR_INSTALL_PROFILE="$PWD/installation.local.json" .venv/bin/python runtime/scripts/doctor.py --integration utm --json
ATR_INSTALL_PROFILE="$PWD/installation.local.json" bash runtime/install/run_local.sh
```

All profile-relative resource paths are relative to the profile's directory;
unknown keys and unresolved placeholders fail. Existing nonempty explicit legacy
configuration wins over profile fields, with provenance/conflicts reported by
doctor. Profiles select resources, never robot identity, calibration or experiment
policy. A Windows drive/UNC path must be validated on Windows, not Linux.
For unconfigured GUI-only use, omit the profile or use
`{"schema":"atr.installation.v1","resources":{}}`. Opening the GUI does not
authorize equipment connections, model loading or an experiment.

Private-resource import is a separate operator-approved step:

1. Inventory source and destination for each run/artifact store, connection record,
   learned policy, model and calibration file; do not copy the old home or `.venv`.
2. Use the existing `ATR_PATH_BINDINGS`/RuntimePaths mapping for private stores
   (see the [cutover runbook](../../system/maintenance/repository_layout_cutover.md));
   the installation profile is not a private-store migration mechanism.
3. Verify robot/camera/device identities, coordinate frames, calibration revisions,
   model licenses/checksums and external source revisions before deliberate reuse.
   OMX and Rebot B601 integrations and their LeRobot sources are not interchangeable.
4. Transfer only approved data to the selected destinations, keep credentials in
   the existing ignored secret stores, and inspect old absolute paths as historical
   references—not executable installation settings. No automatic import occurs.

The [portable-installation evidence](../../system/maintenance/portable_installation_evidence.md)
distinguishes Linux software checks from the outstanding native Windows, GPU/ROS
and hardware acceptance. A lock or a passing doctor alone does not certify those.

Windows native installer dependencies and its independent portable wheelhouse are
not frozen by the Linux core lock. Native path/exit tests are included in Windows
CI; a Linux PowerShell parse is not Windows acceptance. Do not claim a reproducible
Windows portable release until its wheel artifacts and full dependency closure
have been independently frozen and verified.

The doctor command is non-actuating. It does not start printers, robots, model
servers, or camera streams:

```bash
ax4lab doctor
ax4lab doctor --core-only
ax4lab doctor --json
```

Before installing `ax4lab`, run the same check directly:

```bash
.venv/bin/python runtime/scripts/doctor.py
```

Supported distribution model:

- The supported operator install is a source checkout plus `.venv`.
- `python -m build` is kept as a packaging sanity check so Python package
  discovery does not accidentally include runtime artifacts, but the generated
  wheel is not the primary deployment artifact for the full GUI/device system.
- Do not delete the source checkout after installing dependencies; runtime
  config, web templates, graph YAML and install helpers remain under `runtime/`.
  Existing private stores must retain their explicitly selected bindings.

## Windows Quick Start (API Key, No Local AI)

The manual GUI/API recipe below is retained for existing users. It is not the
validated portable deployment target: use Linux for the main runtime and the
Windows bridge bootstrap above for the UTM PC. Native Windows GUI, dependencies
and bridge execution were not tested in this Linux audit.

### 1. Install System Tools

Required:

- Windows 10/11 64-bit
- Git for Windows
- Python 3.11 or newer, installed with the `py` launcher
- PowerShell 5.1 or PowerShell 7+
- An OpenAI API key

Recommended:

- Miniconda or Mambaforge for LeRobot environments
- Microsoft C++ Build Tools only if a Python dependency has to build from source
- PrusaSlicer for local slicing, or Docker Desktop if using Linux containers

### 2. Create the Main Python Environment

Run from PowerShell:

```powershell
cd "$env:USERPROFILE\Documents\AX4LAB"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -r runtime/requirements.txt
```

If your Python command is not `py -3.11`, use the installed Python 3.11+ path.

### 3. Configure API-Key Inference

Create `.env` from the example:

```powershell
Copy-Item .env.example .env
notepad .env
```

Keep real API keys in `.env` only. `.env.example` is tracked by Git and must
keep secret values blank.

For API-only Windows operation, set:

```text
AX4LAB_BACKEND=openai
OPENAI_API_KEY=<your-api-key>
AUTONOMOUS_OPENAI_ORCHESTRATOR_MODEL=gpt-5.5
AUTONOMOUS_OPENAI_E4B_MODEL=gpt-5.5
AUTONOMOUS_MODULE_DESIGNER_MODEL=
```

Leave `AUTONOMOUS_MODULE_DESIGNER_MODEL` blank to use the active backend route.
Set it only when you want Module Designer to force a specific model.

If you want local-first behavior with OpenAI as the final fallback, keep:

```text
AX4LAB_BACKEND=vllm
OPENAI_API_KEY=<your-api-key>
```

AX4LAB then tries the active local backend and its model fallback first; OpenAI is
used only after those fail.

### 4. Start the Server on Windows

From the outer repository root:

```powershell
.\.venv\Scripts\Activate.ps1
Set-Location runtime
python -m app.serve
```

Open:

```text
http://127.0.0.1:7861/
http://127.0.0.1:7861/live
http://127.0.0.1:7861/docs
```

Stop the server with `Ctrl+C` in the PowerShell window.

The Bash `ax4lab` launcher below is for Linux, WSL, or Git Bash. Native Windows can
run the same backend through `python -m app.serve` and the browser UI.

### 5. Windows LeRobot Conda Environment

LeRobot workflows must run outside the main `.venv` in a conda environment.
The AX4LAB bridge invokes them with:

```text
conda run --no-capture-output -n lerobot ...
```

Create the environment:

```powershell
$conda = "$env:USERPROFILE\miniconda3\Scripts\conda.exe"
winget install -e --id Anaconda.Miniconda3 --scope user
& $conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
& $conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
& $conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/msys2
& $conda create -y -n lerobot python=3.10
& $conda run -n lerobot python -m pip install --upgrade pip
```

Clone and install the LeRobot checkout outside this repository, then install it
editable inside the `lerobot` environment according to the LeRobot version you
are using. In AX4LAB, keep these defaults unless your local setup differs:

```yaml
configs/lerobot.yaml:
  conda_executable: conda
  conda_env_name: lerobot
```

When `conda_executable` is left as `conda`, it must resolve through PATH. Otherwise
set an explicit executable path in the installation profile or existing local
configuration. No other user's home or alternate Python environment is selected
automatically; a missing live environment fails preflight.

For SmolVLA training/rollout experiments, the tracked `smolvla_conda_env_name`
uses the isolated `lerobot-pi05-torch211` environment. Prepare that environment
as described in [Requirements](../../docs/project/REQUIREMENTS.md#optional-smolvla-training-branch),
then install the extra and cache the required Hub repos there:

```bash
cd ~/lerobot_pi05
conda run --no-capture-output -n lerobot-pi05-torch211 python -m pip install -e ".[smolvla]"
conda run --no-capture-output -n lerobot-pi05-torch211 hf download lerobot/smolvla_base --max-workers 1
conda run --no-capture-output -n lerobot-pi05-torch211 hf download HuggingFaceTB/SmolVLM2-500M-Video-Instruct --exclude "onnx/*" --max-workers 1
```

Use the `/lerobot` GUI page for port detection, teleoperation, recording,
training, and rollout. Hardware actions still require live confirmation gates.

### 6. Optional Windows Equipment Bridge

If this Windows PC or another Windows PC controls UTM software through PyAutoGUI,
copy the complete bridge package and install it in an interactive Windows session:

```powershell
.\Pyautogui_server_for_window\INSTALL_WINDOWS_BRIDGE.cmd
```

Pair the selected worker with its one-time four-digit console code in Linux
AX4LAB's Lab Equipment Workspace. Do not distribute a model/API key to Windows.
See [Windows bridge setup](../Pyautogui_server_for_window/README.md).

## Linux / WSL Quick Start

Use this path on the Linux main workstation. WSL/Git Bash and hardware stacks
require their own validation; one Linux aarch64 result does not certify them.

```bash
cd /path/to/AX4LAB
bash runtime/install/bootstrap_linux.sh --dry-run
bash runtime/install/bootstrap_linux.sh
# Configure secrets/backend in the newly created ignored .env before use.
```

For API-only operation:

```bash
printf '\nAX4LAB_BACKEND=openai\nOPENAI_API_KEY=<your-api-key>\n' >> .env
bash runtime/install/run_local.sh
```

Alternatively, from the outer repository root, for local-first operation with
OpenAI as final fallback:

```bash
printf '\nAX4LAB_BACKEND=vllm\nOPENAI_API_KEY=<your-api-key>\n' >> .env
bash runtime/install/run_local.sh
```

Install the optional `ax4lab` terminal launcher only on Linux, WSL, or Git Bash:

## Install `ax4lab`

Run from the repository root:

```bash
bash runtime/install/install_cli.sh
```

During initial setup, `bash runtime/install/bootstrap_linux.sh --install-cli`
performs the same explicit launcher opt-in after installing the environment.

The installer creates:

```text
~/.local/bin/ax4lab
```

It also adds `~/.local/bin` to your shell rc file if needed.

If this is the first time `~/.local/bin` was added to PATH, open a new terminal or run:

```bash
source ~/.bashrc
```

For zsh:

```bash
source ~/.zshrc
```

## Start Server

From the selected checkout's outer root (no global alias required):

```bash
bash runtime/install/run_local.sh
```

Stop this foreground server with Ctrl+C. If you explicitly installed the optional
alias and verified its checkout binding, `ax4lab up`/`ax4lab down` remain available.

Separate commands and web ports do not isolate physical equipment. Optional model
services, device bridges and explicitly configured endpoints can still be shared.
Do not run two hardware-owning sessions against the same devices.

Stop the server through that installed alias:

```bash
ax4lab down
```

`ax4lab down` stops this checkout's `app.serve` process. Clean shutdown also releases its LeRobot live subprocesses so stale teleoperation/recording jobs do not hold cameras or serial ports open.

`ax4lab restart` runs `down`, then `up` only if shutdown succeeds. Cleanup retains
the existing behavior, with the explicit force-stop control now named
`AX4LAB_DOWN_FORCE`; the server runs in the foreground like `ax4lab up`. Finish
active work first.

## CLI Help

Show every available command:

```bash
ax4lab
```

## Common Commands

GUI shortcuts and server shutdown:

```bash
ax4lab gui
ax4lab live
ax4lab docs
ax4lab down
```

Runtime status:

```bash
ax4lab status
ax4lab events
```

Run control:

```bash
ax4lab run start test
ax4lab run start live "PLA compression specimen"
ax4lab run pause
ax4lab run resume
ax4lab run stop
ax4lab run safe-stop
```

Inference backend:

```bash
ax4lab backend
ax4lab backend vllm
ax4lab backend nemoclaw
ax4lab backend ollama
ax4lab backend openai
```

GPU/model control:

```bash
ax4lab gpu clear
ax4lab models
ax4lab model load e4b
ax4lab model load 31b
ax4lab model unload e4b
ax4lab model unload 31b
```

### Verify inference before the first experiment

`ax4lab doctor --core-only` checks packages and paths offline. It does **not**
certify an API key, start a model server, or confirm an inference response.

1. For API use, open **Current Models → API Key** and use **Loading**. A
   `registered` key is only stored; its enabled state must also be on.
2. For an existing OpenAI-compatible model server on this or another PC, open
   **Connection Settings ↗ → Local LLM Connection**. Enter its base URL, use
   **Read Models → Add Selected**, assign both roles and update any fallbacks.
   Test each role, then **Save & Apply**. The model weights and serving software
   stay on the model host; AX4LAB needs only network access and credentials.
   Follow [remote endpoint setup](../../docs/gui/gui.md#connect-a-model-server-on-another-machine).
3. If using the supplied managed deployment instead, inspect `ax4lab models`.
   Its configured container must already be running. In this deployment it is
   `openshell-cluster-nemoclaw`; if it is stopped, start that existing container
   with `docker start openshell-cluster-nemoclaw`. A fresh machine must provision
   the model service separately—Python installation does not create this cluster.
   Load the configured models, then check `ax4lab models` again. Both role aliases
   must agree with the served model names. This managed deployment is not required
   for the remote-endpoint route above.
4. Request a short greeting in Live GUI without approving an experiment. Confirm
   an actual response, not just a green package check. To test the local path,
   unload the API-key control first so API fallback cannot hide a local failure.

Backend-specific model settings in `configs/models.yaml` take precedence over
legacy global model variables. Use `AUTONOMOUS_VLLM_E4B_MODEL` for an explicit
vLLM override, for example; do not reuse an Ollama alias for vLLM.

Live GUI chat API:

```bash
ax4lab chat bootstrap "Plan a PLA compression specimen experiment"
# Supported Korean command alias: test mode
ax4lab chat "테스트 모드"
# Supported Korean command alias: run experiment
ax4lab chat "실험 수행"
```

Runtime graph management:

```bash
ax4lab graphs
ax4lab graph show atr_closed_loop
ax4lab graph validate atr_closed_loop
ax4lab graph compile atr_closed_loop
ax4lab graph dry-run atr_closed_loop
ax4lab graph gate atr_closed_loop
ax4lab graph export-yaml atr_closed_loop /tmp/atr_closed_loop.yaml
ax4lab graph import-yaml atr_closed_loop /tmp/atr_closed_loop.yaml
ax4lab graph save-yaml atr_closed_loop /tmp/atr_closed_loop.yaml
ax4lab graph save-yaml atr_closed_loop /tmp/atr_closed_loop.yaml --no-activate
ax4lab graph run atr_closed_loop test "candidate route smoke"
```

Runtime graph commands share the Runtime IDE's `/api/graphs` endpoints. Browser edits appear in `ax4lab graph show`; `save-yaml` changes appear in the browser after reload. `save-yaml` validates, stores a version under `memory/runtime_graph_versions/<graph-id>/`, and activates the graph unless `--no-activate` is passed.

Runtime module management:

```bash
ax4lab modules
ax4lab module show design
ax4lab module validate design
ax4lab module dry-run design
ax4lab module load design
ax4lab module unload design
ax4lab module versions design
ax4lab module version design 20260526T000000000000Z
ax4lab module save-yaml design graphs/modules/design/module.yaml
ax4lab module save-yaml design graphs/modules/design/module.yaml --no-activate
ax4lab module register-generated my_internal_module
ax4lab module create ./my_internal_module.py my_internal_module "My Internal Module"
```

Module management commands share the Module Management Tool's `/api/modules` endpoints. `load` and `unload` change only workspace state, not files or the executable graph. `save-yaml` validates the payload, runs the non-device module dry-run, saves a version under `memory/module_versions/<module-id>/`, and activates the YAML unless `--no-activate` is passed. `register-generated` explicitly approves Module Designer output: it statically checks `handler.py`, switches the handler to `module.generated_adapter`, removes staging-only `runtime.step_complete` internal-step handlers, records a version, and enables execution through the generated adapter wrapper.

`ax4lab module create` sends the Python file to the same `/api/modules` Module
Designer endpoint used by the GUI. The active backend's `module_designer` route
primary model is used first, its model fallback is used second, and if
`backend.fallback: openai` is configured the OpenAI API model is tried last.
The endpoint writes
`graphs/modules/<module-id>/handler.py`, stores the original source beside it
for audit, writes `module.yaml`, saves a version under
`memory/module_versions/<module-id>/`, then leaves execution bound to an
allowlisted handler. If the generated handler is not registered yet, the module
remains `pending_handler_registration` and uses `runtime.step_complete` until
explicit `ax4lab module register-generated <module-id>` approval.

Windows PyAutoGUI bridge standalone deployment:

Do not copy only `install/windows_pyautogui_bridge_server.py`; recording,
image matching, the capability lab, and examples require the complete
`Pyautogui_server_for_window` package. On Windows, run:

```text
Double-click: Pyautogui_server_for_window\INSTALL_WINDOWS_BRIDGE.cmd
```

PowerShell alternative:

```powershell
cd .\Pyautogui_server_for_window
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_bridge.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_supervisor.ps1
```

From the Live GUI, open `Windows Bridge` to scan the internal network, select the
Windows PC, enter its four-digit code, and Pair & Save. Running `program1` is a
separate operator-triggered check, not part of discovery or pairing.

## Optional Piper TTS Voice

LeRobot recording voice cues use Piper English TTS by default when the local
runtime and voice are available. The new public AX4LAB release does not bundle
the `en_US-lessac-medium` model or its config. Review the upstream
[voice model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/lessac/medium/MODEL_CARD)
and linked
[Lessac dataset license](https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html)
before downloading or using it; these links do not establish clearance for
redistribution or your intended use.

If appropriate for your use, explicitly install or repair the local runtime and
voice from the repository root:

```bash
bash runtime/install/install_piper_tts.sh
```

This operator-invoked script installs `piper-tts` into `.venv`, downloads missing
model/config files to `runtime/models/tts/piper/en_US-lessac-medium`, and verifies
synthesis without requiring the LeRobot conda environment to install Piper.
Downloaded voice files remain local. The bootstrap's `--with-piper` option only
installs the `tts` extra; it does not download or test a voice. See the
[voice acquisition notes](../models/tts/piper/README.md).

## Bambu Studio Wrapper

The Bambu Lab X2D bridge resolves the slicer executable in this order:

1. `BAMBU_STUDIO_EXECUTABLE`
2. `install/bambustudio/bambu-studio-wrapper`
3. `PATH` names such as `bambu-studio` or `BambuStudio`

The repository-local wrapper is:

```text
install/bambustudio/bambu-studio-wrapper
```

It does not install Bambu Studio. It finds an existing Bambu Studio executable
from `BAMBU_STUDIO_EXECUTABLE`, `PATH`, common user install locations, `/opt`,
or Flatpak `com.bambulab.BambuStudio`, then forwards all slicer arguments
unchanged.

Recommended Linux setup:

```bash
export BAMBU_STUDIO_EXECUTABLE=/absolute/path/to/bambu-studio
runtime/install/bambustudio/bambu-studio-wrapper --help
ax4lab doctor
```

If `ax4lab doctor` reports that only the wrapper exists but Bambu Studio itself is
missing, install Bambu Studio or set `BAMBU_STUDIO_EXECUTABLE`. The 3DP GUI can
still run MQTT/status checks without slicing, but it cannot generate a
new Bambu-native sliced artifact until the CLI path resolves.

## PrusaSlicer Docker Wrapper

The Prusa MK4S printer bridge can use a Dockerized PrusaSlicer when host-native PrusaSlicer is not installed.

Build the image from the repository root:

```bash
docker build -t atr-prusa-slicer:ubuntu24.04 runtime/install/prusaslicer
```

The wrapper is:

```text
install/prusaslicer/prusa-slicer-docker
```

`configs/devices.yaml` uses this wrapper as the fallback `slicer.executable_path`. If `PRUSA_SLICER_EXECUTABLE` is set, that environment variable overrides the wrapper.

The wrapper mounts this repository into the container and runs PrusaSlicer without shell expansion. Keep generated G-code under repository paths so the container can write it.

For live Prusa MK4S communication, store connection values in:

```text
memory/prusa_connection.json
```

Do not put passwords in docs, prompts, command history, or runtime logs.

## LeRobot D405 / RSUSB Patch Packaging

AX4LAB does not vendor the external LeRobot repository. Live ROBOTIS/RealSense
workflows use a separate checkout, usually `~/lerobot`.

This repository packages the current Spark workstation RealSense D405/RSUSB
compatibility patch at:

```text
patches/lerobot/spark_realsense_d405_rsusb.patch
```

Apply it to the external LeRobot checkout with:

```bash
bash runtime/install/apply_lerobot_d405_patch.sh ~/lerobot
```

The apply script runs `git apply --check` first and stops without changing the
checkout if the patch does not match the current LeRobot branch. If that
happens, update the LeRobot branch/version deliberately; do not replace D405
with `/dev/video*` or OpenCV fallback.

After the patch, RealSense recording keeps the standard 8-bit LeRobot depth
video features and, when AX4LAB passes `ATR_LEROBOT_RAW_DEPTH_DIR`, also writes
16-bit raw Z16 sidecars at
`<dataset>/sidecar/depth_raw/<camera_key>/frame_*.png`. It also writes
`<dataset>/sidecar/depth_raw/transform_manifest.json`, which records the
production RGB-D contract: depth aligned to color, metric scale
`0.001 m/unit`, and fixed visual-depth clipping range `0..2000 mm` unless
`configs/lerobot.yaml` is deliberately changed.

## Environment Variables

The default web port is `7861`. For a local-only custom endpoint, use the same
host/port settings for startup and later CLI requests:

```bash
AX4LAB_HOST=127.0.0.1 AX4LAB_PORT=7862 bash runtime/install/run_local.sh
# In another terminal, target that server:
AX4LAB_HOST=127.0.0.1 AX4LAB_PORT=7862 ax4lab status
```

Use an explicit server URL for a CLI request:

```bash
AX4LAB_URL=http://127.0.0.1:7862 ax4lab status
```

Use a different backend for `run` and `chat` commands. The public
`AX4LAB_BACKEND` setting also selects the server backend; the runtime retains
`AUTONOMOUS_BACKEND` as its internal compatibility key:

```bash
AX4LAB_BACKEND=vllm ax4lab run start test
```

## Reinstall After Moving The Repo

Move source only; do not assume `.venv` or a ROS install tree is relocatable.
The launcher rejects stale/unmarked environment prefixes. At the new location:

```bash
bash runtime/install/bootstrap_linux.sh --rebuild-venv
.venv/bin/python runtime/scripts/doctor.py --core-only
# Only if you explicitly want this checkout's global alias:
bash runtime/install/install_cli.sh
```

The previous environment is preserved in `.venv.backup.*/environment`; rebuild
ROS separately. Update profile/private-store mappings deliberately. The generated
global alias stores its old checkout path and is never repointed automatically.

## Existing `ax4lab` Command Conflict

The installer refuses a different `ax4lab` binding, including at
`~/.local/bin/ax4lab` itself. An existing `atr` command belongs to the original
project and is left untouched.
Force install only if you know the existing command is safe to replace:

```bash
AX4LAB_FORCE_INSTALL=1 bash runtime/install/install_cli.sh
```
