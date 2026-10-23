"""Explicit supersession must not erase or bypass the frozen layout proof."""
import copy
import hashlib
from pathlib import Path
import pytest
from tools.repository_layout.checks import document_locations, audit_document_references


def fixture_manifest():
    identity = {'sha256': hashlib.sha256(b'# Current\n').hexdigest(), 'size': 10, 'mode': '100644'}
    return {'entries': {'docs/paper/evidence/a.md': {'destination': 'docs/paper/evidence/a.md', 'disposition': 'keep'}},
            'latest_main_integration': {'source_base': 'a'*40, 'source_revision': 'b'*40, 'destination_base': 'c'*40,
                'records': [{'old_path': 'docs/paper/evidence/a.md', 'new_path': 'docs/runtime/evidence/a.md',
                    'previous_destination': 'docs/paper/evidence/a.md', 'destination': 'system/runtime/evidence/a.md',
                    'status': 'R100', 'disposition': 'mapped upstream', 'previous_identity': identity, 'current_identity': identity}]}}


def test_explicit_integration_composes_without_mutating_frozen_entries():
    manifest = fixture_manifest(); original = copy.deepcopy(manifest)
    assert document_locations(manifest)['docs/paper/evidence/a.md'] == 'system/runtime/evidence/a.md'
    assert manifest == original


def test_retirement_is_explicit_and_absence_checked(tmp_path):
    manifest = fixture_manifest(); row = manifest['latest_main_integration']['records'][0]
    row.update(status='D', destination=None, new_path=None); row.pop('current_identity')
    assert 'docs/paper/evidence/a.md' not in document_locations(manifest)
    old = tmp_path / row['previous_destination']; old.parent.mkdir(parents=True); old.write_text('# Current\n')
    assert audit_document_references(tmp_path, manifest)['metadata_errors']


@pytest.mark.parametrize('change', ['path', 'duplicate', 'missing_identity', 'revision'])
def test_invalid_supersession_fails_closed(change):
    manifest = fixture_manifest(); phase = manifest['latest_main_integration']; row = phase['records'][0]
    if change == 'path': row['destination'] = '../outside.md'
    elif change == 'duplicate': phase['records'].append(copy.deepcopy(row))
    elif change == 'missing_identity': row.pop('current_identity')
    else: phase['source_revision'] = 'main'
    with pytest.raises(ValueError): document_locations(manifest)


def test_superseded_document_bytes_still_checked(tmp_path):
    manifest = fixture_manifest(); row = manifest['latest_main_integration']['records'][0]
    path = tmp_path / row['destination']; path.parent.mkdir(parents=True); path.write_text('# Current\n')
    assert not audit_document_references(tmp_path, manifest)['metadata_errors']
    path.write_text('# Tampered\n')
    assert audit_document_references(tmp_path, manifest)['metadata_errors']


def test_governance_validator_checks_supersession_not_old_historical_bytes(tmp_path):
    import json
    from scripts.validate_documentation import validate_document
    manifest = fixture_manifest(); row = manifest['latest_main_integration']['records'][0]
    text = ('---\ndoc_type: index\nsubtype: index\nstatus: active\nauthority: navigation\n'
            'audience: [developer]\nscope: [repository]\nsummary: Current index.\n'
            'related_docs: []\nsupersedes: []\n---\n# Current\n')
    row['current_identity'].update(sha256=hashlib.sha256(text.encode()).hexdigest(), size=len(text))
    manifest['historical_documents'] = {row['old_path']: {'sha256': '0'*64}}
    path = tmp_path / row['destination']; path.parent.mkdir(parents=True); path.write_text(text)
    inventory = tmp_path / 'system/maintenance/repository_layout_manifest.json'
    inventory.parent.mkdir(parents=True); inventory.write_text(json.dumps(manifest))
    assert validate_document(path, tmp_path) == []
    path.write_text(text + '\nTampered\n')
    assert any('supersession' in error for error in validate_document(path, tmp_path))


def test_current_document_checks_do_not_invoke_retired_manuscript_validator():
    from tools.repository_layout.checks import CHECKS
    assert not any('paper_publication' in argument for command in CHECKS['8'] for argument in command)


def naming_overlay(manifest, path, previous, current):
    def identity(data):
        return {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data), 'mode': '100644'}
    manifest['ax4lab_naming'] = {
        'base_revision': '35d64d588bca2b8602cd820a35680ebf599e7f69',
        'files': {path: {'previous_identity': identity(previous), 'current_identity': identity(current)}},
    }


def test_naming_overlay_supersedes_current_bytes_without_rewriting_proof(tmp_path):
    manifest = fixture_manifest()
    path = manifest['latest_main_integration']['records'][0]['destination']
    # The actual Git-base bytes need not equal a much older frozen phase receipt.
    naming_overlay(manifest, path, b'# Before branding\n', b'# AX4LAB\n')
    original = copy.deepcopy(manifest)
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.write_bytes(b'# AX4LAB\n')
    assert not audit_document_references(tmp_path, manifest)['metadata_errors']
    assert manifest == original


@pytest.mark.parametrize('tamper', ['bytes', 'mode', 'symlink', 'missing'])
def test_naming_overlay_rejects_modified_current_identity(tmp_path, tamper):
    manifest = {'entries': {}}
    naming_overlay(manifest, 'runtime/app/branding.py', b'old', b'current')
    target = tmp_path / 'runtime/app/branding.py'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'current')
    if tamper == 'bytes': target.write_bytes(b'tampered')
    elif tamper == 'mode': target.chmod(0o755)
    elif tamper == 'symlink':
        target.unlink()
        (target.parent / 'other.py').write_bytes(b'current')
        target.symlink_to('other.py')
    else: target.unlink()
    assert audit_document_references(tmp_path, manifest)['metadata_errors']


@pytest.mark.parametrize('tamper', ['revision', 'path', 'previous', 'current', 'files'])
def test_naming_overlay_invalid_receipts_fail_closed(tmp_path, tamper):
    manifest = {'entries': {}}
    naming_overlay(manifest, 'runtime/app/branding.py', b'old', b'current')
    phase = manifest['ax4lab_naming']
    row = phase['files']['runtime/app/branding.py']
    if tamper == 'revision': phase['base_revision'] = 'main'
    elif tamper == 'path': phase['files']['../escape'] = phase['files'].pop('runtime/app/branding.py')
    elif tamper == 'previous': row['previous_identity']['sha256'] = 'not-a-hash'
    elif tamper == 'current': row['current_identity']['size'] = True
    else: phase['files'] = []
    with pytest.raises(ValueError, match='AX4LAB'):
        audit_document_references(tmp_path, manifest)


def test_governance_validator_uses_naming_overlay_and_detects_tampering(tmp_path):
    import json
    from scripts.validate_documentation import validate_document
    manifest = fixture_manifest()
    path = manifest['latest_main_integration']['records'][0]['destination']
    text = ('---\ndoc_type: index\nsubtype: index\nstatus: active\nauthority: navigation\n'
            'audience: [developer]\nscope: [repository]\nsummary: Current index.\n'
            'related_docs: []\nsupersedes: []\n---\n# AX4LAB\n')
    naming_overlay(manifest, path, b'# Current\n', text.encode())
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.write_text(text)
    inventory = tmp_path / 'system/maintenance/repository_layout_manifest.json'
    inventory.parent.mkdir(parents=True)
    inventory.write_text(json.dumps(manifest))
    assert validate_document(target, tmp_path) == []
    target.write_text(text + '\nTampered\n')
    assert any('AX4LAB' in error for error in validate_document(target, tmp_path))


def release_overlay(manifest, path, previous, current):
    def identity(data):
        return None if data is None else {'sha256': hashlib.sha256(data).hexdigest(),
                                         'size': len(data), 'mode': '100644'}
    manifest['public_release'] = {'base_revision': '9' * 40, 'files': {
        path: {'previous_identity': identity(previous), 'current_identity': identity(current)}}}


def test_public_release_checks_new_bytes_and_preserves_prior_receipts(tmp_path):
    manifest = fixture_manifest()
    path = manifest['latest_main_integration']['records'][0]['destination']
    naming_overlay(manifest, path, b'# Current\n', b'# Before release\n')
    release_overlay(manifest, path, b'# Before release\n', b'# Public\n')
    frozen = copy.deepcopy(manifest)
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.write_bytes(b'# Public\n')
    assert not audit_document_references(tmp_path, manifest)['metadata_errors']
    assert manifest == frozen
    target.write_bytes(b'# Changed without review\n')
    assert audit_document_references(tmp_path, manifest)['metadata_errors']


def test_public_release_retirement_checks_absence_including_dangling_links(tmp_path):
    manifest = fixture_manifest()
    path = manifest['latest_main_integration']['records'][0]['destination']
    release_overlay(manifest, path, b'# Current\n', None)
    assert path not in document_locations(manifest).values()
    assert not audit_document_references(tmp_path, manifest)['metadata_errors']
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.symlink_to('missing')
    assert audit_document_references(tmp_path, manifest)['metadata_errors']


@pytest.mark.parametrize('tamper', ['both_null', 'revision', 'escape', 'size'])
def test_public_release_invalid_receipts_fail_closed(tmp_path, tamper):
    manifest = {'entries': {}}
    release_overlay(manifest, 'runtime/a.py', b'old', b'new')
    phase = manifest['public_release']; row = phase['files']['runtime/a.py']
    if tamper == 'both_null': row.update(previous_identity=None, current_identity=None)
    elif tamper == 'revision': phase['base_revision'] = 'main'
    elif tamper == 'escape': phase['files']['../escape'] = phase['files'].pop('runtime/a.py')
    else: row['current_identity']['size'] = True
    with pytest.raises(ValueError, match='release'):
        audit_document_references(tmp_path, manifest)


def test_public_release_governance_uses_current_receipt(tmp_path):
    import json
    from scripts.validate_documentation import validate_document
    manifest = fixture_manifest()
    path = manifest['latest_main_integration']['records'][0]['destination']
    text = ('---\ndoc_type: index\nsubtype: index\nstatus: active\nauthority: navigation\n'
            'audience: [developer]\nscope: [repository]\nsummary: Public release.\n'
            'related_docs: []\nsupersedes: []\n---\n# Public\n')
    release_overlay(manifest, path, b'# Current\n', text.encode())
    target = tmp_path / path; target.parent.mkdir(parents=True); target.write_text(text)
    inventory = tmp_path / 'system/maintenance/repository_layout_manifest.json'
    inventory.parent.mkdir(parents=True); inventory.write_text(json.dumps(manifest))
    assert validate_document(target, tmp_path) == []
    target.write_text(text + '\nTampered\n')
    assert any('release' in error for error in validate_document(target, tmp_path))
