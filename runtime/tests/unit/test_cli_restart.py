"""Exercise the generated launcher without starting servers or touching devices."""
import os
from pathlib import Path
import subprocess
import sys
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def launcher(tmp_path):
    project = tmp_path / "checkout with spaces"
    (project / 'runtime').mkdir(parents=True)
    python = project / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    # Replace only the external server/process-control interpreter. The real
    # generated shell dispatch, down/up ordering and error handling run intact.
    python.write_text(f"#!{sys.executable}\n" + '''
import os, pathlib, sys
args = sys.argv[1:]
if args == ["-m", "app.serve"]:
    phase = "up"
elif len(args) == 2 and args[0] == "-c" and "targets = []" in args[1]:
    phase = "down"
elif len(args) == 2 and args[0] == "-c" and "pids_by_group = {}" in args[1]:
    phase = "cleanup"
else:
    raise SystemExit("Unexpected process boundary")
with pathlib.Path(os.environ["CLI_TEST_TRACE"]).open("a") as stream:
    stream.write(phase + "\\n")
if os.environ.get("CLI_TEST_FAIL") == phase:
    raise SystemExit(7)
''')
    python.chmod(0o755)
    installer = project / 'runtime/install/install_cli.sh'
    installer.parent.mkdir()
    shutil.copy2(ROOT / 'install/install_cli.sh', installer)
    isolated_home = tmp_path / 'empty-home'
    isolated_home.mkdir()
    target = isolated_home / '.local/bin/atr'
    # Run the real installer with a synthetic home; do not parse implementation
    # text or install into the operator's actual home/profile.
    subprocess.run(['bash', str(installer)], check=True, capture_output=True,
                   env={**os.environ, 'HOME': str(isolated_home), 'PATH': '/usr/bin:/bin',
                        'SHELL': '/bin/bash', 'ATR_FORCE_INSTALL': '0'})
    trace = tmp_path / "trace"
    return target, trace


@pytest.mark.parametrize("failure, expected, code", [
    ("", ["down", "cleanup", "up"], 0),
    ("down", ["down"], 7),
    ("cleanup", ["down", "cleanup"], 7),
    ("up", ["down", "cleanup", "up"], 7),
])
def test_restart_uses_down_then_up_and_propagates_failures(launcher, failure, expected, code):
    command, trace = launcher
    result = subprocess.run([str(command), "restart"], env={**os.environ,
        "CLI_TEST_TRACE": str(trace), "CLI_TEST_FAIL": failure}, capture_output=True, text=True)
    assert result.returncode == code, result.stdout + result.stderr
    assert (trace.read_text().splitlines() if trace.exists() else []) == expected


def test_restart_rejects_extra_arguments_without_stopping(launcher):
    command, trace = launcher
    result = subprocess.run([str(command), "restart", "--force"],
        env={**os.environ, "CLI_TEST_TRACE": str(trace)}, capture_output=True)
    assert result.returncode == 2
    assert not trace.exists()


@pytest.mark.parametrize("command, expected", [("up", ["up"]), ("down", ["down", "cleanup"])])
def test_existing_up_and_down_paths_are_unchanged(launcher, command, expected):
    executable, trace = launcher
    result = subprocess.run([str(executable), command],
        env={**os.environ, "CLI_TEST_TRACE": str(trace), "CLI_TEST_FAIL": ""}, capture_output=True)
    assert result.returncode == 0
    assert trace.read_text().splitlines() == expected
