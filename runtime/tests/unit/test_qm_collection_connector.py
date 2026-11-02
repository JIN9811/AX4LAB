"""Qm collection reuses downloads without executing a save macro."""
import base64
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from device_bridges.windows_pyautogui.bridge import WindowsPyAutoGUIBridge, WindowsPyAutoGUIBridgeConfig
from utils.utm_csv import parse_utm_csv_bytes

CSV = b'Time,Load,Disp,Table\r\nsec,kgf,mm,mm\r\n0,0,0,10\r\n1,2,1,11\r\n2,3,2,12\r\n'


def test_qm_parser_converts_load_not_table_and_preserves_bytes():
    rows, probe = parse_utm_csv_bytes(CSV)
    assert probe['ok'], probe
    assert probe['source_format'] == 'qmesys_raw'
    assert rows[1] == {'time_s': 1.0, 'force_N': 19.6133, 'displacement_mm': 1.0}
    assert probe['sha256'] == hashlib.sha256(CSV).hexdigest()


@pytest.mark.parametrize('bad', [b'nan', b'inf', b'garbage'])
def test_qm_invalid_rows_are_not_silently_accepted(bad):
    _, probe = parse_utm_csv_bytes(CSV.replace(b'1,2,1,11', b'1,'+bad+b',1,11'))
    assert not probe['ok']


@pytest.fixture
def rig(tmp_path, monkeypatch):
    b = WindowsPyAutoGUIBridge(WindowsPyAutoGUIBridgeConfig(
        artifact_dir=tmp_path/'artifacts', connection_memory_path=tmp_path/'connection.json'))
    monkeypatch.setenv(b.config.bridge_url_env, 'http://qm.invalid')
    monkeypatch.setenv(b.config.token_env, 'test-token')
    state = {'requests': [], 'failure': None, 'corrupt': False, 'wrong_identity': False, 'template': 'Compression_{test_no}_{sample_no}.csv'}
    def endpoint(request):
        state['requests'].append(request.url.path)
        assert request.headers['X-Bridge-Token'] == 'test-token'
        if request.url.path == '/raw-data/settings':
            return httpx.Response(200, json={'ok': True, 'settings': {'directory': 'C:/RAW', 'filename_template': state['template']}})
        if request.url.path == '/raw-data/collect':
            body = json.loads(request.content)
            assert body['test_no'] == '11' and body['sample_no'] == '3'
            assert body['not_before_unix'] == 1000
            if state['failure']:
                return httpx.Response(400, json={'ok': False, 'status': state['failure']})
            return httpx.Response(200, json={'ok': True, 'status': 'collected', 'run_id': 'r1', 'specimen_id': 'other' if state['wrong_identity'] else 's1',
                'identity': {'test_no': '11', 'sample_no': '3'},
                'output_artifacts': [{'kind': 'utm_csv', 'artifact_id': 'a1', 'filename': 'a1.csv', 'windows_path': 'C:/RAW/Compression_11_3.csv', 'sha256': hashlib.sha256(CSV).hexdigest()}]})
        if request.url.path == '/artifacts/a1':
            return httpx.Response(200, json={'ok': True, 'filename': 'a1.csv', 'content_base64': base64.b64encode(CSV+b'changed' if state['corrupt'] else CSV).decode()})
        pytest.fail('Unexpected device/UI call: '+request.url.path)
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(endpoint), **kw))
    payload = {'runtime_mode': 'live', 'raw_data_source': 'qm_auto_save', 'test_type': 'Compression', 'test_no': '11', 'sample_no': '3', 'run_id': 'r1', 'specimen_id': 's1', 'not_before_unix': 1000}
    return b, payload, state


def test_existing_run_routes_collection_and_binds_download_for_analysis(rig):
    b, payload, state = rig
    result = b.run(payload)
    assert result['ok'], result
    assert result['status'] == 'data_ready'
    assert result['data_acquisition']['specimen_id'] == 's1'
    assert result['data_acquisition']['run_id'] == 'r1'
    assert Path(result['result_file']).read_bytes() == CSV
    assert result['artifact_pull']['data_artifact_parse_ok']
    assert not result.get('cross_checks', {}).get('physical_motion_started')
    assert state['requests'] == ['/raw-data/settings', '/raw-data/collect', '/artifacts/a1']
    from agents.analysis.agent import AnalysisAgent
    curve, meta = AnalysisAgent()._read_curve_file(result['result_file'])
    assert curve[1]['force_N'] == pytest.approx(19.6133)
    assert curve[1]['displacement_mm'] == 1
    assert meta['column_mapping']['mappings']['Load']['multiplier'] == 9.80665


@pytest.mark.parametrize('field', ['test_type', 'test_no', 'sample_no', 'run_id', 'specimen_id', 'not_before_unix'])
def test_missing_identity_never_contacts_worker(rig, field):
    b, payload, state = rig
    payload.pop(field)
    assert not b.collect_qm_raw_csv(payload)['ok']
    assert state['requests'] == []


def test_virtual_mode_never_reads_real_worker(rig):
    b, payload, state = rig
    payload.update(virtual_bridge_simulation=True, force_live_bridge=True)
    assert not b.run(payload)['ok']
    assert not state['requests']


def test_registered_tool_uses_existing_download_and_profile_dispatch(rig, tmp_path):
    from device_bridges.windows_pyautogui.tools import register_equipment_tools
    from mcp_tools.tool_registry import ToolRegistry
    _, payload, state = rig
    registry = ToolRegistry()
    register_equipment_tools(registry, repo_root=tmp_path)
    result = registry.call('equipment.pyautogui.collect_qm_raw_csv', payload)
    assert result['ok'], result
    assert result['data_acquisition']['specimen_id'] == 's1'
    assert Path(result['result_file']).read_bytes() == CSV
    assert '/execute' not in state['requests']


@pytest.mark.parametrize('unit,force', [(b'N', 2.0), (b'kN', 2000.0)])
def test_qm_unit_conversion_occurs_exactly_once(unit, force):
    rows, probe = parse_utm_csv_bytes(CSV.replace(b'kgf', unit))
    assert probe['ok']
    assert rows[1]['force_N'] == force


def test_analysis_reopening_invalid_qm_file_does_not_use_partial_curve(tmp_path):
    from agents.analysis.agent import AnalysisAgent
    path = tmp_path/'malformed.csv'
    path.write_bytes(CSV+b'3,nan,3,13\r\n')
    curve, meta = AnalysisAgent()._read_curve_file(str(path))
    assert not curve
    assert meta['failure_code'] == 'UTM_DATA_PARSE_FAILED'


@pytest.mark.parametrize('key,value', [('corrupt', True), ('wrong_identity', True), ('template', 'Tension_{test_no}_{sample_no}.csv'), ('failure', 'stale_file')])
def test_invalid_receipt_or_file_never_becomes_data_ready(rig, key, value):
    b, payload, state = rig
    state[key] = value
    result = b.collect_qm_raw_csv(payload)
    assert not result['ok']
    assert result['status'] != 'data_ready'
    assert not result.get('result_file')
    assert '/execute' not in state['requests']
