#!/usr/bin/env bash
# Explicit AX4LAB launch only; never consult any global CLI or active environment.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd -- "${RUNTIME_ROOT}/.." && pwd)"
source "${SCRIPT_DIR}/venv_guard.sh"
unset PYTHONHOME PYTHONPATH
export PYTHONNOUSERSITE=1
normalize_installation_profile
check_checkout_venv "${REPO_ROOT}/.venv"
cd "${RUNTIME_ROOT}"
exec "${REPO_ROOT}/.venv/bin/python" -m app.serve "$@"
