import json
import gzip
from pathlib import Path


def test_distribution_contains_serial_code_descriptors_and_web_assets():
    root=Path(__file__).resolve().parents[2]
    contract=json.loads((root/'distribution-files.json').read_text())
    assert 'device_bridges.serial_communication' in contract['packages']
    for source in (root/'device_bridges/serial_communication').rglob('*'):
        if source.is_file() and '__pycache__' not in source.parts:
            relative=source.relative_to(root).as_posix()
            assert relative in contract['sdist'],relative
            if source.suffix in {'.py','.yaml','.svg'}:
                assert relative in contract['wheel'],relative
    for source in ['web/templates/serial.html','web/static/serial_workspace.js',
                   'web/static/serial_workspace.css','web/static/workspace_icons/serial.svg']:
        assert source in contract['bound_resources']
        assert source in contract['sdist']


def test_qm_model_deployment_is_complete_and_preserves_corrected_geometry():
    root=Path(__file__).resolve().parents[2]
    contract=json.loads((root/'distribution-files.json').read_text())
    assets=root/'device_bridges/serial_communication/modules/qm_indicator/views/model'
    for path in assets.parent.rglob('*'):
        if path.is_file():
            relative=path.relative_to(root).as_posix()
            assert relative in contract['wheel'],relative
            assert relative in contract['sdist'],relative
    scene=json.loads(gzip.decompress((assets/'scene.json.gz').read_bytes()))
    names={p['name'] for p in scene['parts']}
    assert 'TopPlate' in names
    assert 'IndicatorCable' not in names
    assert 'IndicatorCableSocket' not in names
    assert 'IndicatorColumnPort' not in names
    assert 'CabinetBadge' not in names
    assert 'CabinetWarranty' not in names
    assert scene['kinematics']['frame_y_offset'] == -.095
    assert scene['kinematics']['default_gap'] == .030
    for part in scene['parts']:
        if part.get('texture'):
            assert (assets/part['texture']).is_file()
