import json
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
