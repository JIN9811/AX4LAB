"""External evidence must be explicit, exact and free of path/credential metadata."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shlex

import pytest

from utils.installation_profile import load_installation_profile
from utils.runtime_paths import RuntimePaths


def paths(root):
    return RuntimePaths(*[root for _ in range(11)])


def test_manifest_records_selected_git_and_model_without_private_metadata(tmp_path):
    from utils.installation_manifest import build_manifest
    source = tmp_path / 'private checkout'
    source.mkdir()
    subprocess.run(['git', 'init', str(source)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Fixture', '-c',
                    'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-m', 'fixture'],
                   check=True, capture_output=True)
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    subprocess.run(['git', '-C', str(source), 'remote', 'add', 'origin',
                    'https://private-user:SECRET@example.invalid/private/repo'], check=True)
    (source / 'dirty').write_text('private contents')
    model = tmp_path / 'secret model name.pt'
    model.write_bytes(b'model fixture')
    profile_path = tmp_path / 'installation.local.json'
    profile_path.write_text(json.dumps({'schema': 'atr.installation.v1', 'resources': {
        'lerobot': {'source_root': str(source)}, 'utm': {'yolo_model_path': str(model)}}}))
    profile = load_installation_profile(paths(tmp_path), environ={})
    payload = build_manifest(paths(tmp_path), profile)
    assert payload['external']['lerobot.source_root'] == {
        'status': 'revision_only', 'revision': revision, 'dirty': None, 'dirty_status': 'unverified'}
    assert payload['external']['utm.yolo_model_path'] == {
        'status': 'hashed', 'sha256': hashlib.sha256(b'model fixture').hexdigest(), 'size': 13}
    assert payload['external']['isaac.lab_root']['status'] == 'not_configured'
    encoded = json.dumps(payload)
    for private in [str(tmp_path), 'SECRET', 'private-user', 'private contents', 'secret model name']:
        assert private not in encoded


def test_manifest_does_not_treat_missing_or_parent_git_as_evidence(tmp_path):
    from utils.installation_manifest import build_manifest
    subprocess.run(['git', 'init', str(tmp_path)], check=True, capture_output=True)
    nested = tmp_path / 'not-a-checkout'
    nested.mkdir()
    (tmp_path / 'installation.local.json').write_text(json.dumps({
        'schema': 'atr.installation.v1', 'resources': {
            'lerobot': {'source_root': str(nested)}, 'utm': {'yolo_model_path': 'missing.pt'}}}))
    payload = build_manifest(paths(tmp_path), load_installation_profile(paths(tmp_path), environ={}))
    assert payload['external']['lerobot.source_root']['status'] == 'unverified'
    assert payload['external']['utm.yolo_model_path']['status'] == 'missing'
    assert payload['core_lock']['status'] == 'missing'


@pytest.mark.parametrize('filter_type', ['clean', 'process'])
def test_manifest_never_executes_repository_defined_filters(tmp_path, filter_type):
    from utils.installation_manifest import build_manifest
    source = tmp_path / 'filtered repository'
    source.mkdir()
    def git(*args):
        return subprocess.run(['git', '-C', str(source), *args], check=True, capture_output=True)
    git('init')
    (source / '.gitattributes').write_text('tracked.txt filter=sentinel\n')
    (source / 'tracked.txt').write_text('original contents\n')
    git('add', '.')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        'commit', '-m', 'fixture')
    sentinel = tmp_path / 'filter-executed'
    command = f'touch {shlex.quote(str(sentinel))}; ' + ('cat' if filter_type == 'clean' else 'exit 1')
    git('config', f'filter.sentinel.{filter_type}', command)
    tracked = source / 'tracked.txt'
    tracked.write_text('modified contents\n')  # Same byte count forces content comparison.
    os.utime(tracked, (tracked.stat().st_atime, tracked.stat().st_mtime + 2))
    (tmp_path / 'installation.local.json').write_text(json.dumps({
        'schema': 'atr.installation.v1', 'resources': {'lerobot': {'source_root': str(source)}}}))
    receipt = build_manifest(paths(tmp_path), load_installation_profile(paths(tmp_path), environ={}))
    assert not sentinel.exists(), 'manifest inspection executed a repository-defined filter'
    assert receipt['external']['lerobot.source_root']['dirty'] is None
    assert receipt['external']['lerobot.source_root']['dirty_status'] == 'unverified'
