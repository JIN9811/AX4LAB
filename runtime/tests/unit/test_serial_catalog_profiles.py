from pathlib import Path
import shutil

import pytest


def catalog():
    from device_bridges.serial_communication.catalog import ModuleCatalog
    return ModuleCatalog()


def test_discovery_does_not_import_protocol_and_third_folder_needs_no_registration(tmp_path):
    c = catalog()
    assert {m['id'] for m in c.list()} == {'qm_indicator', 'cas_mwii_plus'}
    source = c.get('cas_mwii_plus').root
    target = tmp_path / 'third_device'
    shutil.copytree(source, target)
    manifest = target / 'module.yaml'
    manifest.write_text(manifest.read_text().replace('cas_mwii_plus', 'third_device'))
    (target / 'protocol.py').write_text('raise RuntimeError("must not import on scan")')
    from device_bridges.serial_communication.catalog import ModuleCatalog
    dynamic = ModuleCatalog(tmp_path)
    assert dynamic.list()[0]['id'] == 'third_device'
    shutil.rmtree(target)
    dynamic.refresh()
    assert dynamic.list() == []


def test_bad_manifest_does_not_break_valid_module_and_icon_cannot_escape(tmp_path):
    c = catalog()
    shutil.copytree(c.get('cas_mwii_plus').root, tmp_path / 'cas_mwii_plus')
    bad = tmp_path / 'bad'
    bad.mkdir()
    (bad / 'module.yaml').write_text('id: [invalid')
    from device_bridges.serial_communication.catalog import ModuleCatalog
    dynamic = ModuleCatalog(tmp_path)
    assert len(dynamic.list()) == 1
    assert dynamic.errors
    icon = dynamic.get('cas_mwii_plus').root / 'icon.svg'
    icon.unlink()
    icon.symlink_to('/etc/passwd')
    with pytest.raises(ValueError):
        dynamic.icon('cas_mwii_plus')


def test_set_survives_reload_and_rejects_stale_edits(tmp_path):
    from device_bridges.serial_communication.profiles import ProfileStore
    from device_bridges.serial_communication.errors import SerialError
    path = tmp_path / 'config.json'
    store = ProfileStore(path)
    p = store.create({'name': 'Scale', 'module_id': 'cas_mwii_plus', 'settings': {}})
    saved = store.update(p['id'], {'settings': {'port': '/dev/example', 'baudrate': 9600}}, p['revision'])
    assert ProfileStore(path).get(p['id'])['settings']['port'] == '/dev/example'
    with pytest.raises(SerialError, match='revision'):
        store.update(p['id'], {'name': 'Stale'}, p['revision'])
    store.delete(p['id'], saved['revision'])
    assert ProfileStore(path).list() == []


def test_corrupt_config_is_not_replaced(tmp_path):
    from device_bridges.serial_communication.profiles import ProfileStore
    from device_bridges.serial_communication.errors import SerialError
    path = tmp_path / 'config.json'
    path.write_text('broken')
    with pytest.raises(SerialError):
        ProfileStore(path).list()
    assert path.read_text() == 'broken'


def test_duplicate_and_malformed_field_modules_are_isolated(tmp_path):
    import yaml
    from device_bridges.serial_communication.catalog import ModuleCatalog
    source = catalog().get('cas_mwii_plus').root
    for name in ('one','two','bad'):
        shutil.copytree(source,tmp_path/name)
    m=tmp_path/'bad/module.yaml'
    data=yaml.safe_load(m.read_text());data['id']='bad';data['fields'][1].pop('options')
    m.write_text(yaml.safe_dump(data))
    c=ModuleCatalog(tmp_path)
    assert c.list()==[]
    assert len(c.errors)==2


def test_missing_icon_uses_default_path(tmp_path):
    import yaml
    from device_bridges.serial_communication.catalog import ModuleCatalog
    shutil.copytree(catalog().get('cas_mwii_plus').root,tmp_path/'scale')
    m=tmp_path/'scale/module.yaml'
    data=yaml.safe_load(m.read_text());data.pop('icon');m.write_text(yaml.safe_dump(data))
    assert ModuleCatalog(tmp_path).icon('cas_mwii_plus').name=='icon.svg'


def test_failed_atomic_set_preserves_previous_config(tmp_path,monkeypatch):
    from device_bridges.serial_communication import profiles
    from device_bridges.serial_communication.errors import SerialError
    store=profiles.ProfileStore(tmp_path/'config.json')
    p=store.create({'name':'A','module_id':'cas_mwii_plus','settings':{}})
    previous=store.path.read_bytes()
    def failed(*args):
        raise OSError('disk full')
    monkeypatch.setattr(profiles.os,'replace',failed)
    with pytest.raises(SerialError,match='not saved'):
        store.update(p['id'],{'name':'B'},1)
    assert store.path.read_bytes()==previous
