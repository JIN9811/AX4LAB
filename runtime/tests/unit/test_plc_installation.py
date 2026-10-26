"""PLC dependency checks must work without connecting to laboratory devices."""

import builtins
from pathlib import Path
import shutil
import socket
import subprocess
from types import SimpleNamespace

import pytest

from scripts import doctor as module


RUNTIME = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("extra", [[], ["--extra", "plc"]])
def test_frozen_default_install_includes_plc_without_an_extra(extra):
    """Catch the live transport dependency being excluded from core installation."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required to exercise the frozen installer export")
    result = subprocess.run(
        [uv, "export", "--offline", "--frozen", "--project", str(RUNTIME),
         "--no-dev", "--no-emit-project", "--no-hashes", "--no-header", "--no-annotate", *extra],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "pymcprotocol==0.3.0" in result.stdout.splitlines()


@pytest.mark.parametrize("installed", [False, True])
def test_core_doctor_checks_plc_without_importing_or_connecting(monkeypatch, installed):
    """Catch a missing PLC SDK being reported as a successful core installation."""
    def find_spec(name):
        if name == "pymcprotocol" and not installed:
            return None
        return SimpleNamespace(origin=f"/fixture/site-packages/{name}/__init__.py")

    def forbidden(*args, **kwargs):
        raise AssertionError("Installation checks must not connect to devices")

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "pymcprotocol" or name.startswith("pymcprotocol."):
            raise AssertionError("Installation checks must not import the PLC SDK")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(module.PathFinder, "find_spec", find_spec)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    doctor = module.Doctor()
    doctor.check_imports()
    if installed:
        assert doctor.exit_code() == 0
        assert any(row["name"] == "package: pymcprotocol" and row["level"] == "ok"
                   for row in doctor.results)
    else:
        assert doctor.exit_code() == 1
        assert any(row["name"] == "python imports" and "pymcprotocol" in row["detail"]
                   for row in doctor.results)
