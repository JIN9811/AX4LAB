<!-- atr-doc
doc_type: reference
subtype: api
status: active
authority: descriptive
audience: [user, operator, developer]
scope: [ax4lab_cli, installation, gui_navigation]
summary: Quick reference for AX4LAB installation, daily commands, configuration and run control.
source_of_truth:
  - runtime/install/bootstrap_linux.sh
  - runtime/install/install_cli.sh
  - runtime/install/run_local.sh
  - runtime/utils/launcher_settings.py
  - runtime/app/main.py
last_verified: 2026-10-24
verified_against: working-tree
related_docs:
  - runtime/install/README.md
  - docs/tutorials/first_autonomous_run.en.md
  - docs/tutorials/user_manual.en.md
  - system/runtime/runtime_ide.md
supersedes: []
-->

# AX4LAB Cheat Sheet

Common commands for an installed Linux checkout. Run setup commands from the
repository root, where `README.md` and `runtime/` are located. API commands need
a running server; use a second terminal while `ax4lab up` runs in the first.

## Install and start

Requires Python 3.11+ and `uv`. See [installation](../runtime/install/README.md)
for prerequisites and optional device dependencies.

```bash
# Preview setup without installing anything.
bash runtime/install/bootstrap_linux.sh --dry-run --install-cli

# Install the checkout environment and optional ax4lab command.
bash runtime/install/bootstrap_linux.sh --install-cli
```

Open a new terminal if the installer added `~/.local/bin` to `PATH`.
For an already installed environment, add only the command with
`bash runtime/install/install_cli.sh`.

| Task | Command |
|---|---|
| Show all commands | `ax4lab --help` |
| Start the server in the foreground | `ax4lab up` |
| Start without installing the global command | `bash runtime/install/run_local.sh` |
| Stop this checkout's server | `ax4lab down` |
| Stop, then start this checkout's server | `ax4lab restart` |

Starting the server is not starting an experiment. Finish or safely stop active
work before `down` or `restart`; server shutdown also releases its live LeRobot
subprocesses. The original `atr` command belongs to the original installation.

## Daily checks and screens

Default address: **http://127.0.0.1:7861**. Replace the host and port below if configured.

| Task | Command or route |
|---|---|
| Main GUI | `ax4lab gui` → `/` |
| Live GUI with orchestrator auto-bootstrap | `ax4lab live` → `/live?auto=1` |
| Read-only session replay | `/replay` |
| Runtime IDE / module management | `/ide` / `/module-management` |
| Printer / robot / UTM workspace | `/printer` / `/lerobot` / `/equipment/windows` |
| Vision / knowledge / BO workspace | `/device-bridge/vision-utm` / `/knowledge` / `/bo` |
| Interactive API reference | `ax4lab docs` → `/docs` |
| Current run state | `ax4lab status` |
| Recent events | `ax4lab events` |
| Installed core dependencies and paths | `ax4lab doctor --core-only` |
| Configured integration diagnostics | `ax4lab doctor` |
| Machine-readable diagnostics | `ax4lab doctor --json` |

## Backend and model selection

| Task | Command |
|---|---|
| Inspect current backend state | `ax4lab backend` |
| Switch to external API | `ax4lab backend openai` |
| Switch to local vLLM | `ax4lab backend vllm` |
| Inspect managed models | `ax4lab models` |
| Load a configured model | `ax4lab model load <model-alias>` |
| Unload a configured model | `ax4lab model unload <model-alias>` |

Configure credentials before using an API. Backend switches affect runtime state;
model loading consumes memory. Avoid switching or unloading during an active run.
`ollama` and `nemoclaw` are also supported backend names.

## Run control

Prefer the [first-run walkthrough](tutorials/first_autonomous_run.en.md) for initial
setup and approval. These commands change the current workflow, not just the display.

| Task | Command |
|---|---|
| Start a new workflow | `ax4lab run start <mode> "Research goal"` |
| Pause the workflow | `ax4lab run pause` |
| Resume an eligible paused or recoverable workflow | `ax4lab run resume` |
| Stop the workflow | `ax4lab run stop` |
| Request the runtime safe-stop path | `ax4lab run safe-stop` |

Modes: `test`, `live`, `replay`, `fault-injection`. **Test mode can use real
equipment**, depending on the selected profile. Check the admitted contract and
device state before starting or resuming. Software pause/stop is not a physical
emergency stop. Opening `/replay` for read-only review is distinct from starting
a workflow with mode `replay`.

## Inspect modules and graphs

Replace angle-bracket placeholders with IDs returned by the listing commands.
These checks do not start a device workflow; graph dry-run records a validation gate.

| Task | Command |
|---|---|
| List modules / inspect one | `ax4lab modules` / `ax4lab module show <module-id>` |
| Validate a module | `ax4lab module validate <module-id>` |
| Inspect its configured step order | `ax4lab module dry-run <module-id>` |
| List graphs / inspect one | `ax4lab graphs` / `ax4lab graph show <graph-id>` |
| Validate a graph | `ax4lab graph validate <graph-id>` |
| Simulate graph transitions | `ax4lab graph dry-run <graph-id>` |
| Inspect the recorded gate | `ax4lab graph gate <graph-id>` |

Loading modules, saving/activating graphs and running workflows are separate
actions. See [Runtime IDE](../system/runtime/runtime_ide.md) for editing and activation.

## Settings and common fixes

Edit the repository-root `.env` for persistent launcher defaults. Shell environment
values override `.env`; explicit `AX4LAB_URL` changes the CLI target, not the server bind address.

| Setting | Purpose |
|---|---|
| `AX4LAB_PORT=7861` | Server port and default CLI target port |
| `AX4LAB_HOST=127.0.0.1` | Bind locally; use a LAN-accessible bind only when needed |
| `AX4LAB_BACKEND=openai` | Startup/default request backend; alternatives above |
| `AX4LAB_URL=http://127.0.0.1:7861` | Optional explicit CLI target, including a remote server |

| Symptom | Check or action |
|---|---|
| `ax4lab` not found | Open a new terminal; check `command -v ax4lab` and the installation step above. |
| Connection refused or wrong server | Check `ax4lab up`, `.env`, shell overrides and `AX4LAB_URL`. |
| Environment moved with the checkout | Stop its server, then run `bash runtime/install/bootstrap_linux.sh --rebuild-venv --install-cli`; reinclude any optional dependency flags. The old environment is backed up. |
| Missing device/model dependency | Run `ax4lab doctor`; follow [installation profiles](../runtime/install/README.md) for that integration. |

Keep credentials in local configuration. Separate `atr`/`ax4lab` commands and web
ports do not isolate shared devices: do not run two sessions controlling the same hardware.

## Verification and further reading

Checked against the local AX4LAB working tree on 24 October 2026, including its
uncommitted naming changes. Command syntax comes from the launcher and bootstrap
scripts listed in the metadata; this reference does not certify hardware readiness.

[Installation](../runtime/install/README.md) ·
[Operator walkthroughs](tutorials/user_manual.en.md) ·
[Documentation index](README.md)
