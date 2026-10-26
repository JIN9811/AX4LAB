#!/usr/bin/env bash
# File purpose:
# - Install the user-level `ax4lab` launcher for this AX4LAB checkout.
#
# Inputs/outputs:
# - Input: this repository path, resolved from the script location.
# - Output: ~/.local/bin/ax4lab and an optional shell PATH block.
#
# Modification guide:
# - Safe places to edit: command names and usage text.
# - Risky places to edit: PROJECT_DIR resolution and PATH update logic.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PROJECT_DIR="$(cd -- "${RUNTIME_DIR}/.." && pwd)"
INSTALL_DIR="${HOME}/.local/bin"
TARGET="${INSTALL_DIR}/ax4lab"
SHELL_NAME="$(basename "${SHELL:-bash}")"
RC_FILE="${HOME}/.bashrc"

if [[ "${SHELL_NAME}" == "zsh" ]]; then
  RC_FILE="${HOME}/.zshrc"
fi

existing_ax4lab="$(command -v ax4lab || true)"
PROJECT_QUOTED="$(printf '%q' "${PROJECT_DIR}")"
RUNTIME_QUOTED="$(printf '%q' "${RUNTIME_DIR}")"
conflict=0
if [[ -n "${existing_ax4lab}" && "${existing_ax4lab}" != "${TARGET}" ]]; then conflict=1; fi
if [[ -e "${TARGET}" || -L "${TARGET}" ]]; then
  if [[ -L "${TARGET}" || ! -f "${TARGET}" ]] ||
     ! grep -Fxq "PROJECT_DIR=${PROJECT_QUOTED}" "${TARGET}" ||
     ! grep -Fxq "RUNTIME_DIR=${RUNTIME_QUOTED}" "${TARGET}"; then conflict=1; fi
fi
if [[ "${conflict}" == 1 && "${AX4LAB_FORCE_INSTALL:-0}" != "1" ]]; then
  cat >&2 <<EOF
Refusing to overwrite existing ax4lab command: ${existing_ax4lab}
Set AX4LAB_FORCE_INSTALL=1 to override this check.
EOF
  exit 1
fi

mkdir -p "${INSTALL_DIR}"
temporary_launcher="$(mktemp "${INSTALL_DIR}/.ax4lab.XXXXXX")"
trap 'rm -f -- "${temporary_launcher}"' EXIT

cat > "${temporary_launcher}" <<EOF
#!/usr/bin/env bash
# Managed by AX4LAB/install/install_cli.sh
set -euo pipefail

PROJECT_DIR=${PROJECT_QUOTED}
RUNTIME_DIR=${RUNTIME_QUOTED}
unset PYTHONHOME PYTHONPATH
export PYTHONNOUSERSITE=1
BASE_URL=""
DEFAULT_BACKEND=""

usage() {
  cat <<'USAGE'
Usage:
  ax4lab up
  ax4lab down
  ax4lab restart
  ax4lab gui
  ax4lab live
  ax4lab docs
  ax4lab doctor [--core-only] [--hardware] [--json]
  ax4lab status
  ax4lab events
  ax4lab backend [vllm|openai]
  ax4lab graphs
  ax4lab graph show|validate|compile|dry-run|gate|versions <graph-id>
  ax4lab graph version <graph-id> <version-id>
  ax4lab graph export-yaml <graph-id> [output-file]
  ax4lab graph import-yaml <graph-id> <yaml-file>
  ax4lab graph save-yaml <graph-id> <yaml-file> [--no-activate]
  ax4lab graph run <graph-id> [test|live|replay|fault-injection] [goal text...]
  ax4lab run start [test|live|replay|fault-injection] [goal text...]
  ax4lab run pause|resume|stop|safe-stop
  ax4lab gpu clear
  ax4lab models
  ax4lab model load|unload <endpoint-id>
  ax4lab modules
  ax4lab knowledge graph health|import|query|neo4j-start|neo4j-stop|print-env [options]
  ax4lab knowledge graphify-scan [options]
  ax4lab knowledge graphify-import [options]
  ax4lab module show|validate|dry-run|load|unload|versions|register-generated <module-id>
  ax4lab module version <module-id> <version-id>
  ax4lab module save-yaml <module-id> <yaml-file> [--no-activate]
  ax4lab module create <python-file> [module-id] [label text...]
  ax4lab chat "message"
  ax4lab chat bootstrap [goal text...]

Commands:
  up          Start the AX4LAB GUI server.
  down        Stop this checkout's GUI server process; server shutdown releases LeRobot live subprocesses.
  restart     Run down, then up only after down succeeds; same stop/start behavior.
  gui         Open the main GUI URL.
  live        Open the Live GUI URL with auto bootstrap.
  docs        Open FastAPI docs.
  doctor      Run non-actuating fresh-install diagnostics for Python deps, CLI binding, ignored secrets, slicers, LeRobot, RealSense, and model config.
  status      Print /api/state.
  events      Print recent structured events.
  backend     Show current state, or select the vllm/local or openai/API endpoint branch.
  graphs      List Runtime IDE graph configs from /api/graphs.
  graph show  Print one active graph payload.
  graph validate
              Validate active graph handlers/modules/routes.
  graph compile
              Compile-check active graph without starting agents or hardware.
  graph dry-run
              Run non-device transition simulation and record active dry-run gate.
  graph gate  Show live dry-run gate status for the active graph.
  graph versions|version
              List/read saved graph versions.
  graph export-yaml|import-yaml|save-yaml
              Round-trip graph YAML through the same Runtime IDE API. save-yaml validates, versions, and activates unless --no-activate is passed.
  graph run   Start a specific saved active graph through /api/graphs/{graph_id}/run.
  run start   Start a workflow through /api/run/start. Default mode is test.
  run pause   Pause the current run.
  run resume  Resume the current run.
  run stop    Stop the current run.
  run safe-stop
              Request safe stop.
  gpu clear   Run the same GPU Clear action as the GUI.
  models      Print registered local endpoint loading status.
  model load  Load one managed local endpoint (for example, local-main).
  model unload
              Unload one managed vLLM model.
  modules     List Runtime IDE module catalog entries.
  knowledge graph
              Operate optional Knowledge graph backend. Supports health, import, query, neo4j-start, neo4j-stop, and print-env.
  knowledge graphify-scan
              Build Graphify-compatible project graph artifacts under memory/knowledge/graphify.
  knowledge graphify-import
              Import project graph artifacts into the optional Knowledge graph backend.
  module show Print one module.yaml payload through the API.
  module validate
              Validate one module payload without executing devices.
  module dry-run
              Show configured internal module step order.
  module load|unload
              Load or unload a module in the Module Management workspace state without deleting files.
  module versions|version
              List/read saved module.yaml versions.
  module save-yaml
              Validate, dry-run, version, and activate a module YAML file unless --no-activate is passed.
  module register-generated
              Approve a Module Designer handler.py after static safety checks and activate module.generated_adapter.
  module create
              Upload a Python file to Module Designer; the active backend converts it to AX4LAB protocol and catalogs it.
  Graph CUI commands intentionally use the same /api/graphs endpoints as Runtime IDE, so GUI/CUI state is cross-reflected after reload.
  Module CUI commands intentionally use the same /api/modules endpoints as Module Management Tool, so GUI/CUI state is cross-reflected after reload.
  chat        Send a message to the Live GUI orchestrator session.
  chat bootstrap
              Trigger Live GUI orchestrator bootstrap from the terminal.

Environment:
  AX4LAB_HOST/AX4LAB_PORT
                Server bind and derived API target. Environment > .env > system.yaml.
                Default API target: http://127.0.0.1:7861; wildcard binds use loopback.
  AX4LAB_URL    Explicit client-only API base URL override; does not change server bind.
  AX4LAB_BACKEND   Backend used by run/chat commands. Default: vllm; set openai to skip local inference.
  AX4LAB_DOWN_FORCE
                Set to 0 to avoid SIGKILL fallback when stopping the GUI server.
USAGE
}

python_bin() {
  if [[ -x "\${PROJECT_DIR}/.venv/bin/python" ]]; then
    printf '%s\n' "\${PROJECT_DIR}/.venv/bin/python"
    return 0
  fi
  command -v python3 || true
}

require_python() {
  local py
  py="\$(python_bin)"
  if [[ -z "\${py}" ]]; then
    echo "error: python3 or project .venv is required for this command" >&2
    exit 1
  fi
  printf '%s\n' "\${py}"
}

pretty_json() {
  local py
  py="\$(python_bin)"
  if [[ -n "\${py}" ]]; then
    "\${py}" -m json.tool 2>/dev/null || cat
  else
    cat
  fi
}

api_get() {
  curl -fsS "\${BASE_URL}\${1}" | pretty_json
  printf '\n'
}

api_post() {
  local path="\${1}"
  local body="\${2}"
  curl -fsS -X POST "\${BASE_URL}\${path}" -H "Content-Type: application/json" -d "\${body}" | pretty_json
  printf '\n'
}

api_put() {
  local path="\${1}"
  local body="\${2}"
  curl -fsS -X PUT "\${BASE_URL}\${path}" -H "Content-Type: application/json" -d "\${body}" | pretty_json
  printf '\n'
}

api_post_text() {
  local path="\${1}"
  local body="\${2}"
  curl -fsS -X POST "\${BASE_URL}\${path}" -H "Content-Type: application/json" -d "\${body}"
  printf '\n'
}

open_url() {
  local url="\${1}"
  if command -v xdg-open >/dev/null 2>&1; then
    nohup xdg-open "\${url}" >/dev/null 2>&1 &
    echo "Opened: \${url}"
  else
    echo "\${url}"
  fi
}

load_client_settings() {
  local py settings
  local -a values
  py="\$(require_python)"
  settings="\$("\${py}" "\${RUNTIME_DIR}/utils/launcher_settings.py" "\${PROJECT_DIR}" "\${RUNTIME_DIR}")" || return
  mapfile -t values <<< "\${settings}"
  BASE_URL="\${values[0]}"
  DEFAULT_BACKEND="\${values[1]}"
}

start_server() {
  exec bash "\${RUNTIME_DIR}/install/run_local.sh"
}

stop_server() {
  local py
  py="\$(require_python)"
  AX4LAB_PROJECT_DIR="\${PROJECT_DIR}" "\${py}" -c 'import os, signal, sys, time

project = os.path.realpath(os.environ["AX4LAB_PROJECT_DIR"])
force = os.environ.get("AX4LAB_DOWN_FORCE", "1") != "0"
targets = []

for name in os.listdir("/proc"):
    if not name.isdigit():
        continue
    pid = int(name)
    if pid in {os.getpid(), os.getppid()}:
        continue
    proc_dir = f"/proc/{pid}"
    try:
        raw = open(os.path.join(proc_dir, "cmdline"), "rb").read()
    except OSError:
        continue
    parts = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
    if not parts:
        continue
    if parts[1:3] != ["-m", "app.serve"]:
        continue
    try:
        cwd = os.path.realpath(os.readlink(os.path.join(proc_dir, "cwd")))
    except OSError:
        cwd = ""
    # The guarded launcher always runs in this exact runtime directory.
    # A path mentioned in arguments, a sibling path, or an unrelated module
    # does not establish process ownership.
    if cwd == os.path.join(project, "runtime"):
        targets.append(pid)

targets = sorted(set(targets))
if not targets:
    print("No AX4LAB GUI server process found.")
    sys.exit(0)

for pid in targets:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        print(f"error: cannot stop pid {pid}: {exc}", file=sys.stderr)

deadline = time.time() + 5.0
remaining = []
while time.time() < deadline:
    remaining = []
    for pid in targets:
        try:
            os.kill(pid, 0)
            remaining.append(pid)
        except ProcessLookupError:
            pass
    if not remaining:
        break
    time.sleep(0.1)

if remaining and force:
    for pid in remaining:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    time.sleep(0.2)
    remaining = []
    for pid in targets:
        try:
            os.kill(pid, 0)
            remaining.append(pid)
        except ProcessLookupError:
            pass

if remaining:
    print(f"GUI server stop requested, but still running: {remaining}", file=sys.stderr)
    sys.exit(1)

print("Stopped AX4LAB GUI server process(es): " + ", ".join(str(pid) for pid in targets))
'
}

json_backend() {
  local py="\$(require_python)"
  ATR_BACKEND_VALUE="\${1}" "\${py}" -c 'import json, os; print(json.dumps({"backend": os.environ["ATR_BACKEND_VALUE"]}))'
}

json_model() {
  local py="\$(require_python)"
  ATR_ENDPOINT_VALUE="\${1}" "\${py}" -c 'import json, os; print(json.dumps({"endpoint_id": os.environ["ATR_ENDPOINT_VALUE"]}))'
}

json_module_create() {
  local py="\$(require_python)"
  ATR_MODULE_FILE="\${1}" ATR_MODULE_ID="\${2}" ATR_MODULE_LABEL="\${3}" ATR_MODULE_CATEGORY_VALUE="\${ATR_MODULE_CATEGORY:-}" ATR_MODULE_HANDLER_VALUE="\${ATR_MODULE_HANDLER:-runtime.step_complete}" "\${py}" -c 'import json, os, pathlib
path = pathlib.Path(os.environ["ATR_MODULE_FILE"])
module_id = os.environ["ATR_MODULE_ID"] or path.stem.replace("-", "_")
label = os.environ["ATR_MODULE_LABEL"] or module_id.replace("_", " ").title()
print(json.dumps({"module_id": module_id, "label": label, "category": os.environ.get("ATR_MODULE_CATEGORY_VALUE", ""), "handler": os.environ.get("ATR_MODULE_HANDLER_VALUE", "runtime.step_complete"), "source_filename": path.name, "source_text": path.read_text(encoding="utf-8"), "notes": "Created from ax4lab module create", "transform_with_llm": True, "transform_model": os.environ.get("AUTONOMOUS_MODULE_DESIGNER_MODEL", "")}, ensure_ascii=False))'
}

json_module_save_yaml() {
  local py="\$(require_python)"
  ATR_MODULE_YAML_FILE="\${1}" ATR_MODULE_ACTIVATE="\${2}" "\${py}" -c 'import json, os, pathlib, yaml; path=pathlib.Path(os.environ["ATR_MODULE_YAML_FILE"]); raw=yaml.safe_load(path.read_text(encoding="utf-8")) or {}; module=raw.get("module", raw) if isinstance(raw, dict) else raw; print(json.dumps({"module": module, "reason": "ax4lab module save-yaml", "author": "ax4lab-cli", "activate": os.environ["ATR_MODULE_ACTIVATE"] != "0"}, ensure_ascii=False))'
}

json_run_start() {
  local py="\$(require_python)"
  ATR_MODE_VALUE="\${1}" ATR_GOAL_VALUE="\${2}" ATR_BACKEND_VALUE="\${3}" "\${py}" -c 'import json, os; print(json.dumps({"mode": os.environ["ATR_MODE_VALUE"], "goal": os.environ["ATR_GOAL_VALUE"], "backend": os.environ["ATR_BACKEND_VALUE"], "fault": "none", "fault_stage": ""}, ensure_ascii=False))'
}

json_graph_dry_run() {
  local py="\$(require_python)"
  ATR_START_STAGE_VALUE="\${1}" ATR_MAX_STEPS_VALUE="\${2}" "\${py}" -c 'import json, os; print(json.dumps({"start_stage": os.environ["ATR_START_STAGE_VALUE"], "max_steps": int(os.environ["ATR_MAX_STEPS_VALUE"])}))'
}

json_graph_run() {
  local py="\$(require_python)"
  ATR_MODE_VALUE="\${1}" ATR_GOAL_VALUE="\${2}" ATR_BACKEND_VALUE="\${3}" "\${py}" -c 'import json, os; print(json.dumps({"mode": os.environ["ATR_MODE_VALUE"], "goal": os.environ["ATR_GOAL_VALUE"], "backend": os.environ["ATR_BACKEND_VALUE"], "fault": "none", "fault_stage": ""}, ensure_ascii=False))'
}

json_graph_yaml_import() {
  local py="\$(require_python)"
  ATR_GRAPH_YAML_FILE="\${1}" "\${py}" -c 'import json, os, pathlib; print(json.dumps({"yaml_text": pathlib.Path(os.environ["ATR_GRAPH_YAML_FILE"]).read_text(encoding="utf-8")}, ensure_ascii=False))'
}

json_graph_save_yaml() {
  local py="\$(require_python)"
  ATR_GRAPH_YAML_FILE="\${1}" ATR_GRAPH_ACTIVATE="\${2}" "\${py}" -c 'import json, os, pathlib, yaml; path=pathlib.Path(os.environ["ATR_GRAPH_YAML_FILE"]); raw=yaml.safe_load(path.read_text(encoding="utf-8")) or {}; graph=raw.get("graph", raw) if isinstance(raw, dict) else raw; print(json.dumps({"graph": graph, "reason": "ax4lab graph save-yaml", "author": "ax4lab-cli", "activate": os.environ["ATR_GRAPH_ACTIVATE"] != "0"}, ensure_ascii=False))'
}

json_chat_message() {
  local py="\$(require_python)"
  ATR_MESSAGE_VALUE="\${1}" ATR_BACKEND_VALUE="\${2}" "\${py}" -c 'import json, os; print(json.dumps({"message": os.environ["ATR_MESSAGE_VALUE"], "goal": "Terminal Live GUI session", "backend": os.environ["ATR_BACKEND_VALUE"], "session_id": "ax4lab-cli", "constraints": {"runtime_contract": "existing_stage_enum_only", "require_operator_approval": True}}, ensure_ascii=False))'
}

json_chat_bootstrap() {
  local py="\$(require_python)"
  ATR_GOAL_VALUE="\${1}" ATR_BACKEND_VALUE="\${2}" "\${py}" -c 'import json, os; print(json.dumps({"goal": os.environ["ATR_GOAL_VALUE"], "backend": os.environ["ATR_BACKEND_VALUE"], "session_id": "ax4lab-cli", "constraints": {"runtime_contract": "existing_stage_enum_only", "require_operator_approval": True}}, ensure_ascii=False))'
}

if [[ "\$#" -eq 0 ]]; then
  usage
  exit 0
fi

if [[ "\${1:-}" == "-h" || "\${1:-}" == "--help" || "\${1:-}" == "help" ]]; then
  usage
  exit 0
fi

case "\${1:-}" in
  up|down|restart|doctor) ;;
  *) load_client_settings ;;
esac

case "\${1:-}" in
  restart)
    [[ "\$#" -eq 1 ]] || { usage; exit 2; }
    "\$0" down
    exec "\$0" up
    ;;
  up)
    if [[ "\$#" -eq 1 ]]; then
      start_server
    fi
    ;;
  down)
    if [[ "\$#" -eq 1 ]]; then
      stop_server
      exit 0
    fi
    ;;
  gui)
    open_url "\${BASE_URL}/"
    exit 0
    ;;
  live)
    open_url "\${BASE_URL}/live?auto=1&backend=\${DEFAULT_BACKEND}"
    exit 0
    ;;
  docs)
    open_url "\${BASE_URL}/docs"
    exit 0
    ;;
  doctor)
    py="\$(require_python)"
    shift 1
    cd "\${RUNTIME_DIR}"
    exec "\${py}" scripts/doctor.py "\$@"
    ;;
  status)
    api_get "/api/state"
    exit 0
    ;;
  events)
    api_get "/api/events/recent"
    exit 0
    ;;
  backend)
    if [[ "\$#" -eq 1 ]]; then
      api_get "/api/state"
    elif [[ "\$#" -eq 2 ]]; then
      case "\${2}" in
        vllm|openai) ;;
        *) echo "Runtime backend must be vllm or openai." >&2; exit 2 ;;
      esac
      api_post "/api/runtime/backend" "\$(json_backend "\${2}")"
    else
      usage
      exit 2
    fi
    exit 0
    ;;
  graphs)
    api_get "/api/graphs"
    exit 0
    ;;
  graph)
    case "\${2:-}" in
      show)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_get "/api/graphs/\${3}"
        exit 0
        ;;
      validate)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_post "/api/graphs/\${3}/validate" "{}"
        exit 0
        ;;
      compile)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_post "/api/graphs/\${3}/compile" "{}"
        exit 0
        ;;
      dry-run)
        [[ -n "\${3:-}" ]] || { usage; exit 2; }
        start_stage="\${4:-idle}"
        max_steps="\${5:-24}"
        [[ "\$#" -le 5 ]] || { usage; exit 2; }
        api_post "/api/graphs/\${3}/dry-run" "\$(json_graph_dry_run "\${start_stage}" "\${max_steps}")"
        exit 0
        ;;
      gate)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_get "/api/graphs/\${3}/dry-run-gate"
        exit 0
        ;;
      versions)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_get "/api/graphs/\${3}/versions"
        exit 0
        ;;
      version)
        [[ -n "\${3:-}" && -n "\${4:-}" && "\$#" -eq 4 ]] || { usage; exit 2; }
        api_get "/api/graphs/\${3}/versions/\${4}"
        exit 0
        ;;
      export-yaml)
        [[ -n "\${3:-}" ]] || { usage; exit 2; }
        [[ "\$#" -le 4 ]] || { usage; exit 2; }
        if [[ -n "\${4:-}" ]]; then
          curl -fsS -X POST "\${BASE_URL}/api/graphs/\${3}/export-yaml" -H "Content-Type: application/json" -d "{}" -o "\${4}"
          echo "Wrote graph YAML: \${4}"
        else
          api_post_text "/api/graphs/\${3}/export-yaml" "{}"
        fi
        exit 0
        ;;
      import-yaml)
        [[ -n "\${3:-}" && -n "\${4:-}" && "\$#" -eq 4 ]] || { usage; exit 2; }
        api_post "/api/graphs/\${3}/import-yaml" "\$(json_graph_yaml_import "\${4}")"
        exit 0
        ;;
      save-yaml)
        [[ -n "\${3:-}" && -n "\${4:-}" ]] || { usage; exit 2; }
        [[ "\$#" -le 5 ]] || { usage; exit 2; }
        activate="1"
        if [[ "\${5:-}" == "--no-activate" ]]; then
          activate="0"
        elif [[ -n "\${5:-}" ]]; then
          usage
          exit 2
        fi
        api_put "/api/graphs/\${3}" "\$(json_graph_save_yaml "\${4}" "\${activate}")"
        exit 0
        ;;
      run)
        [[ -n "\${3:-}" ]] || { usage; exit 2; }
        mode="\${4:-test}"
        if [[ "\$#" -ge 5 ]]; then
          goal="\${*:5}"
        else
          goal=""
        fi
        api_post "/api/graphs/\${3}/run" "\$(json_graph_run "\${mode}" "\${goal}" "\${DEFAULT_BACKEND}")"
        exit 0
        ;;
      *)
        usage
        exit 2
        ;;
    esac
    ;;
  run)
    case "\${2:-}" in
      start)
        mode="\${3:-test}"
        if [[ "\$#" -ge 4 ]]; then
          goal="\${*:4}"
        else
          goal=""
        fi
        api_post "/api/run/start" "\$(json_run_start "\${mode}" "\${goal}" "\${DEFAULT_BACKEND}")"
        ;;
      pause)
        api_post "/api/run/pause" "{}"
        ;;
      resume)
        api_post "/api/run/resume" "{}"
        ;;
      stop)
        api_post "/api/run/stop" "{}"
        ;;
      safe-stop)
        api_post "/api/run/safe-stop" "{}"
        ;;
      *)
        usage
        exit 2
        ;;
    esac
    exit 0
    ;;
  gpu)
    if [[ "\${2:-}" == "clear" && "\$#" -eq 2 ]]; then
      api_post "/api/runtime/gpu-clear" "{}"
      exit 0
    fi
    ;;
  models)
    api_get "/api/runtime/models"
    exit 0
    ;;
  model)
    if [[ "\${2:-}" == "load" && -n "\${3:-}" && "\$#" -eq 3 ]]; then
      api_post "/api/runtime/models/load" "\$(json_model "\${3}")"
      exit 0
    fi
    if [[ "\${2:-}" == "unload" && -n "\${3:-}" && "\$#" -eq 3 ]]; then
      api_post "/api/runtime/models/unload" "\$(json_model "\${3}")"
      exit 0
    fi
    ;;
  modules)
    api_get "/api/modules"
    exit 0
    ;;
  knowledge)
    if [[ "\${2:-}" == "graph" && "\$#" -ge 3 ]]; then
      py="\$(require_python)"
      shift 2
      cd "\${RUNTIME_DIR}"
      exec "\${py}" "\${RUNTIME_DIR}/scripts/knowledge_graph_cli.py" "\$@"
    fi
    if [[ "\${2:-}" == "graphify-scan" && "\$#" -ge 2 ]]; then
      py="\$(require_python)"
      shift 2
      cd "\${RUNTIME_DIR}"
      exec "\${py}" "\${RUNTIME_DIR}/scripts/knowledge_graphify_scan.py" "\$@"
    fi
    if [[ "\${2:-}" == "graphify-import" || "\${2:-}" == "graph-import" ]]; then
      py="\$(require_python)"
      shift 2
      cd "\${RUNTIME_DIR}"
      exec "\${py}" "\${RUNTIME_DIR}/scripts/knowledge_graph_import.py" "\$@"
    fi
    usage
    exit 2
    ;;
  module)
    case "\${2:-}" in
      show)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_get "/api/modules/\${3}"
        exit 0
        ;;
      validate)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_post "/api/modules/\${3}/validate" "{}"
        exit 0
        ;;
      dry-run)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_post "/api/modules/\${3}/dry-run" "{}"
        exit 0
        ;;
      load)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_post "/api/modules/\${3}/load" "{}"
        exit 0
        ;;
      unload)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_post "/api/modules/\${3}/unload" "{}"
        exit 0
        ;;
      versions)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_get "/api/modules/\${3}/versions"
        exit 0
        ;;
      version)
        [[ -n "\${3:-}" && -n "\${4:-}" && "\$#" -eq 4 ]] || { usage; exit 2; }
        api_get "/api/modules/\${3}/versions/\${4}"
        exit 0
        ;;
      save-yaml)
        [[ -n "\${3:-}" && -n "\${4:-}" ]] || { usage; exit 2; }
        [[ "\$#" -le 5 ]] || { usage; exit 2; }
        activate="1"
        if [[ "\${5:-}" == "--no-activate" ]]; then
          activate="0"
        elif [[ -n "\${5:-}" ]]; then
          usage
          exit 2
        fi
        api_put "/api/modules/\${3}" "\$(json_module_save_yaml "\${4}" "\${activate}")"
        exit 0
        ;;
      register-generated)
        [[ -n "\${3:-}" && "\$#" -eq 3 ]] || { usage; exit 2; }
        api_post "/api/modules/\${3}/register-generated" "{}"
        exit 0
        ;;
      create)
        [[ -n "\${3:-}" ]] || { usage; exit 2; }
        file="\${3}"
        module_id="\${4:-}"
        if [[ "\$#" -ge 5 ]]; then
          label="\${*:5}"
        else
          label=""
        fi
        api_post "/api/modules" "\$(json_module_create "\${file}" "\${module_id}" "\${label}")"
        exit 0
        ;;
      *)
        usage
        exit 2
        ;;
    esac
    ;;
  chat)
    if [[ "\${2:-}" == "bootstrap" ]]; then
      shift 2 || true
      goal="\${*:-Terminal Live GUI session}"
      api_post "/api/planning/bootstrap" "\$(json_chat_bootstrap "\${goal}" "\${DEFAULT_BACKEND}")"
      exit 0
    fi
    if [[ "\$#" -ge 2 ]]; then
      shift 1
      api_post "/api/planning/message" "\$(json_chat_message "\$*" "\${DEFAULT_BACKEND}")"
      exit 0
    fi
    ;;
esac

usage
exit 2
EOF

chmod +x "${temporary_launcher}"
mv -fT -- "${temporary_launcher}" "${TARGET}"

path_line='export PATH="$HOME/.local/bin:$PATH"'
if [[ ! -f "${RC_FILE}" ]]; then
  touch "${RC_FILE}"
fi

if ! grep -Fq 'HOME/.local/bin' "${RC_FILE}"; then
  cat >> "${RC_FILE}" <<EOF

# AX4LAB CLI PATH
${path_line}
# end AX4LAB CLI PATH
EOF
  path_updated="yes"
else
  path_updated="no"
fi

cat <<EOF
Installed ax4lab launcher:
  ${TARGET}

Project bound to:
  ${PROJECT_DIR}

PATH rc file:
  ${RC_FILE} (updated: ${path_updated})

Usage:
  ax4lab up
  ax4lab down
  ax4lab restart
  ax4lab doctor
  ax4lab status
  ax4lab models
  ax4lab live
  ax4lab gui
EOF
