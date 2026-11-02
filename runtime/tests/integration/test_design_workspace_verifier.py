"""The operator verifier runs real API and registered graphs with retained evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_offline_verifier_retains_hash_parity_and_denies_hardware(tmp_path):
    runtime = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(runtime/'scripts/verify_design_workspace.py'),
        '--output-root', str(tmp_path/'evidence'), '--parity', 'simple_cubic',
        '--skip-regressions'], cwd=runtime, env={**os.environ, 'PYTHONPATH': str(runtime)},
        capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads((tmp_path/'evidence/summary.json').read_text())
    assert summary['hardware_predispatch_denied'] is True
    row = summary['parity'][0]
    assert row['geometry_id'] == 'simple_cubic' and row['ok']
    assert row['api_stl_sha256'] == row['agent_stl_sha256']
    assert row['api_request_sha256'] == row['agent_request_sha256']
    assert row['specimen_reused'] and row['manufacturing_status'] == 'review_required'
    assert list((tmp_path/'evidence').rglob('receipt.json'))
    assert list((tmp_path/'evidence').rglob('preview.png'))
