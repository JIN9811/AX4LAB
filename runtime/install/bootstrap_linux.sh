#!/usr/bin/env bash
# Checkout-local core setup. Does not launch services, models, or devices.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd -- "${RUNTIME_ROOT}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
UV_BIN="${UV_BIN:-uv}"
INSTALL_CLI=0
REBUILD=0
DRY_RUN=0
SYSTEM_PACKAGES=0
EXTRAS=()
usage() {
  cat <<'USAGE'
Usage: bash runtime/install/bootstrap_linux.sh [options]
  --dry-run               Print the plan without running commands or writing files.
  --install-cli           Opt in to installing ~/.local/bin/ax4lab; collisions fail.
  --skip-cli              Legacy spelling for the default (no global CLI).
  --rebuild-venv          Preserve the old .venv in a backup, then create a fresh one.
  --with-piper           Install locked TTS Python dependencies only; no voice download/test.
  --with-local-pyautogui  Install locked desktop Python dependencies only.
  --with-realsense        Select the optional native RealSense Python wheel.
  --with-plc              Compatibility flag; PLC dependencies are included by default.
  --with-system-packages  Opt in to sudo apt-get for X11 tools (network/system changes).
Environment: PYTHON_BIN (default python3), UV_BIN (default uv).
Requires uv already installed. Core includes BoTorch/Torch; downloads can be large.
No models, credentials, calibration, or datasets are copied. No server is started.
USAGE
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-cli) INSTALL_CLI=1 ;;
    --skip-cli) INSTALL_CLI=0 ;;
    --rebuild-venv) REBUILD=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --with-piper) EXTRAS+=(--extra tts) ;;
    --with-local-pyautogui) EXTRAS+=(--extra desktop) ;;
    --with-realsense) EXTRAS+=(--extra realsense) ;;
    --with-plc) EXTRAS+=(--extra plc) ;;
    --with-system-packages) SYSTEM_PACKAGES=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
  shift
done
run() {
  printf '+ '; printf '%q ' "$@"; printf '\n'
  if [[ "${DRY_RUN}" != 1 ]]; then "$@"; fi
}
source "${SCRIPT_DIR}/venv_guard.sh"
normalize_installation_profile
# Resolve before changing directory. A bare name lets uv select a managed
# interpreter that differs from the one the shell uses for our identity check.
# Keep symlinks intact so a caller-selected virtualenv keeps its semantics.
if ! selected_python="$(type -P -- "${PYTHON_BIN}")"; then
  echo "Python executable not found: ${PYTHON_BIN}. Set PYTHON_BIN to an installed Python executable." >&2
  exit 1
fi
PYTHON_BIN="$(realpath -ms -- "${selected_python}")"
cd "${REPO_ROOT}"
unset PYTHONHOME PYTHONPATH VIRTUAL_ENV
export PYTHONNOUSERSITE=1
export UV_PROJECT_ENVIRONMENT="${REPO_ROOT}/.venv"
export UV_CACHE_DIR="${REPO_ROOT}/.cache/uv"
export UV_PYTHON_DOWNLOADS=never
echo "Repository: ${REPO_ROOT}"
echo "Network: locked PyPI dependencies (including Torch); no model downloads. No service startup."
if [[ -e .venv || -L .venv ]]; then
  if [[ "${REBUILD}" == 1 ]]; then
    if [[ "${DRY_RUN}" == 1 ]]; then
      echo '+ Preserve .venv in .venv.backup.XXXXXX/environment before rebuilding'
    else
      backup="$(mktemp -d "${REPO_ROOT}/.venv.backup.XXXXXX")"
      mv -- .venv "${backup}/environment"
      echo "Previous environment preserved: ${backup}/environment"
    fi
  elif [[ "${DRY_RUN}" != 1 ]]; then
    check_checkout_venv "${REPO_ROOT}/.venv"
    check_requested_interpreter "${REPO_ROOT}/.venv" "${PYTHON_BIN}"
  fi
fi
# --frozen alone does not detect stale metadata; check the lock first.
run "${UV_BIN}" lock --check --project "${RUNTIME_ROOT}" --python "${PYTHON_BIN}"
if [[ ! -d .venv || "${REBUILD}" == 1 ]]; then
  run "${UV_BIN}" venv --python "${PYTHON_BIN}" "${REPO_ROOT}/.venv"
fi
if [[ "${DRY_RUN}" != 1 ]]; then
  printf '%s\n' "${REPO_ROOT}/.venv" > .venv/.atr-prefix
  check_checkout_venv "${REPO_ROOT}/.venv"
  check_requested_interpreter "${REPO_ROOT}/.venv" "${PYTHON_BIN}"
fi
# Source launch needs no editable build; third-party dependencies are all locked.
# Pin sync to the already validated environment interpreter, never a replacement
# request. The caller's interpreter selection was checked before this operation.
run "${UV_BIN}" sync --frozen --project "${RUNTIME_ROOT}" --python "${REPO_ROOT}/.venv/bin/python" --no-default-groups --no-install-project "${EXTRAS[@]}"
if [[ "${DRY_RUN}" != 1 ]]; then
  check_checkout_venv "${REPO_ROOT}/.venv"
  check_requested_interpreter "${REPO_ROOT}/.venv" "${PYTHON_BIN}"
fi
if [[ "${SYSTEM_PACKAGES}" == 1 ]]; then
  run sudo apt-get update
  run sudo apt-get install -y python3-tk scrot wmctrl xdotool
fi
if [[ ! -f .env ]]; then run cp .env.example .env; fi
cd "${RUNTIME_ROOT}"
run "${REPO_ROOT}/.venv/bin/python" -m utils.installation_manifest
run "${REPO_ROOT}/.venv/bin/python" "${RUNTIME_ROOT}/scripts/doctor.py" --core-only
if [[ "${INSTALL_CLI}" == 1 ]]; then run bash "${SCRIPT_DIR}/install_cli.sh"; fi
echo "Setup passed. Explicit launch: bash runtime/install/run_local.sh"
