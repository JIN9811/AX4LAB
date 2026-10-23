#!/usr/bin/env bash
# Shared checkout environment boundary. No discovery, activation, or fallback.
normalize_installation_profile() {
  if [[ -n "${ATR_INSTALL_PROFILE:-}" ]]; then
    case "${ATR_INSTALL_PROFILE}" in
      '~') ATR_INSTALL_PROFILE="${HOME}" ;;
      '~/'*) ATR_INSTALL_PROFILE="${HOME}/${ATR_INSTALL_PROFILE:2}" ;;
    esac
    ATR_INSTALL_PROFILE="$(realpath -ms -- "${ATR_INSTALL_PROFILE}")" || return
    export ATR_INSTALL_PROFILE
  fi
}

check_checkout_venv() {
  local venv="$1" actual
  if [[ -L "${venv}" || ! -x "${venv}/bin/python" || ! -f "${venv}/.atr-prefix" ]] ||
     [[ "$(<"${venv}/.atr-prefix")" != "${venv}" ]]; then
    echo "Missing, unverified, or moved .venv. Run runtime/install/bootstrap_linux.sh (use --rebuild-venv for an existing environment)." >&2
    return 1
  fi
  actual="$("${venv}/bin/python" -I -c 'import sys; print(sys.prefix)')" || return
  if [[ "${actual}" != "${venv}" ]]; then
    echo "Stale Python prefix. Run runtime/install/bootstrap_linux.sh --rebuild-venv." >&2
    return 1
  fi
}

check_requested_interpreter() {
  local venv="$1" requested="$2" probe selected installed
  probe='import json, os, sys; print(json.dumps([sys.implementation.name, sys.version, os.path.realpath(sys._base_executable)]))'
  selected="$("${requested}" -I -c "${probe}")" || return
  installed="$("${venv}/bin/python" -I -c "${probe}")" || return
  if [[ "${selected}" != "${installed}" ]]; then
    echo "Requested Python differs from this .venv. Run runtime/install/bootstrap_linux.sh --rebuild-venv to preserve it before replacement." >&2
    return 1
  fi
}
