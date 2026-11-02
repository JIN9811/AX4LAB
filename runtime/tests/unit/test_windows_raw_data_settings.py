"""Windows-local RAW configuration must not choose arbitrary/stale CSVs."""
import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture
def worker(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[2] / 'Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py'
    spec = importlib.util.spec_from_file_location('raw_data_worker_test', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ARTIFACT_ROOT', tmp_path/'artifacts')
    return module


def configure(worker, tmp_path):
    folder = tmp_path/'RAW'
    folder.mkdir()
    result = worker._save_raw_data_settings({'directory':str(folder),'filename_template':'Compression_{test_no}_{sample_no}.csv'})
    assert result['ok']
    return folder


def test_settings_persist_and_search_exact_identity(worker, tmp_path):
    folder = configure(worker, tmp_path)
    expected = folder/'Compression_11_3.csv'
    expected.write_text('Time,Load,Disp,Table\nsec,kgf,mm,mm\n0,3.8,0,0\n1,0,8,8\n')
    (folder/'Compression_11_30.csv').write_text('wrong specimen')
    assert worker._raw_data_settings()['settings']['directory'] == str(folder)
    result = worker._search_raw_data({'test_no':'11','sample_no':'3'})
    assert result['ok'] and result['file']['name'] == 'Compression_11_3.csv'
    assert expected.read_text().startswith('Time,Load')


@pytest.mark.parametrize('template', ['../{test_no}_{sample_no}.csv', '*{test_no}_{sample_no}.csv','{unknown}.csv','Compression.csv'])
def test_invalid_template_keeps_saved_settings(worker, tmp_path, template):
    configure(worker, tmp_path)
    before = worker._raw_data_settings()
    assert not worker._save_raw_data_settings({'directory':str(tmp_path),'filename_template':template})['ok']
    assert worker._raw_data_settings() == before


def test_missing_identity_and_traversal_never_select_latest(worker, tmp_path):
    folder = configure(worker, tmp_path)
    (folder/'Compression_11_3.csv').write_text('data')
    for identity in ({}, {'test_no':'11','sample_no':'4'}, {'test_no':'../11','sample_no':'3'}):
        assert not worker._search_raw_data(identity)['ok']


def test_readonly_search_does_not_register_or_actuate(worker, tmp_path, monkeypatch):
    folder = configure(worker, tmp_path)
    (folder/'Compression_11_3.csv').write_text('data')
    monkeypatch.setattr(worker, '_load_pyautogui', lambda: pytest.fail('Must not load desktop controls'))
    before = dict(worker.ARTIFACT_INDEX)
    assert worker._search_raw_data({'test_no':'11','sample_no':'3'})['ok']
    assert dict(worker.ARTIFACT_INDEX) == before


def test_collect_requires_fresh_identity_and_preserves_original(worker, tmp_path):
    import time
    folder = configure(worker, tmp_path)
    expected = folder/'Compression_11_3.csv'
    text = 'Time,Load,Disp,Table\nsec,kgf,mm,mm\n0,3.8,0,0\n1,0,8,8\n'
    expected.write_text(text)
    args = {'test_no':'11','sample_no':'3','run_id':'run-1','specimen_id':'spec-3','stable_for_sec':.01}
    assert not worker._collect_raw_data(args)['ok']
    assert not worker._collect_raw_data({**args,'not_before_unix':time.time()+5})['ok']
    result = worker._collect_raw_data({**args,'not_before_unix':time.time()-10})
    assert result['ok'], result
    art = result['output_artifacts'][0]
    assert worker.ARTIFACT_INDEX[art['artifact_id']]['path'] != str(expected)
    assert expected.read_text() == text
    assert art['parse_ok'] and art['row_count_probe'] == 2


def test_symlink_outside_raw_folder_rejected(worker, tmp_path):
    folder = configure(worker, tmp_path)
    external = tmp_path/'outside.csv'
    external.write_text('not in raw folder')
    (folder/'Compression_11_3.csv').symlink_to(external)
    assert not worker._search_raw_data({'test_no':'11','sample_no':'3'})['ok']


def test_collect_rejects_file_modified_during_stability_check(worker, tmp_path, monkeypatch):
    import time
    folder = configure(worker, tmp_path)
    target = folder/'Compression_11_3.csv'
    target.write_text('initial')
    monkeypatch.setattr(worker.time, 'sleep', lambda _: target.write_text('still writing'))
    result = worker._collect_raw_data({'test_no':'11','sample_no':'3','run_id':'r','specimen_id':'s','not_before_unix':time.time()-10})
    assert result['status'] == 'file_changing'
    assert not (worker.ARTIFACT_ROOT/'r').exists()


def test_qmesys_units_and_invalid_numeric_rows(worker):
    good = b'Time,Load,Disp,Table\nsec,kgf,mm,mm\n0,3.8,0,0.08\n1,0,8,8\n'
    probe = worker._probe_qmesys_csv(good)
    assert probe['ok'] and probe['data_quality']['force_scale_to_N'] == 9.80665
    assert probe['units']['Load'] == 'kgf'
    assert not worker._probe_qmesys_csv(good.replace(b'kgf',b'unknown'))['ok']
    assert not worker._probe_qmesys_csv(good.replace(b'3.8',b'nan'))['ok']


def test_raw_routes_require_auth_remotely_and_collect_even_locally(worker):
    handler = object.__new__(worker.Handler)
    handler.headers = {}
    handler.client_address = ('192.0.2.1',123)
    for path, method in [('/raw-data/settings','GET'),('/raw-data/settings','POST'),('/raw-data/search','POST'),('/raw-data/collect','POST')]:
        assert not handler._has_route_access(path,method)
    handler.client_address = ('127.0.0.1',123)
    assert handler._has_route_access('/raw-data/settings','POST')
    assert handler._has_route_access('/raw-data/search','POST')
    assert not handler._has_route_access('/raw-data/collect','POST')
