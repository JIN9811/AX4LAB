"""Opt-in local evidence receipt. Never copy URLs, paths, environment or secrets.

This records bytes/revisions, not compatibility or hardware readiness. Only
explicitly selected source/model resources are inspected; no home discovery.
"""
from __future__ import annotations

import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile

from utils.installation_profile import InstallationProfile, load_installation_profile
from utils.runtime_paths import RuntimePaths, current_paths


def _file_evidence(value: str | Path) -> dict:
    if not value:
        return {'status': 'not_configured'}
    path = Path(value)
    if not path.is_file():
        return {'status': 'missing'}
    try:
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        return {'status': 'hashed', 'sha256': digest.hexdigest(), 'size': path.stat().st_size}
    except OSError:
        return {'status': 'unverified'}


def _git_evidence(value: str) -> dict:
    if not value:
        return {'status': 'not_configured'}
    path = Path(value)
    if not path.is_dir():
        return {'status': 'missing'}
    # Do not mistake an enclosing checkout for this selected source repository.
    if not (path / '.git').exists():
        return {'status': 'unverified'}
    def git(*args):
        return subprocess.check_output(
            ['git', '--no-optional-locks', '-c', 'core.fsmonitor=false', '-C', str(path), *args], text=True,
            stderr=subprocess.DEVNULL, timeout=10,
            env={key: val for key, val in os.environ.items() if not key.startswith('GIT_')}).strip()
    try:
        revision = git('rev-parse', '--verify', 'HEAD')
        if not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', revision):
            return {'status': 'unverified'}
        # Even read-only `git status` can execute configured clean/filter-process
        # commands. Record HEAD only; do not assert working-tree cleanliness.
        return {'status': 'revision_only', 'revision': revision,
                'dirty': None, 'dirty_status': 'unverified'}
    except (OSError, subprocess.SubprocessError):
        return {'status': 'unverified'}


def build_manifest(paths: RuntimePaths, profile: InstallationProfile) -> dict:
    resources = profile.resources
    selected = {
        'lerobot.source_root': _git_evidence(resources.lerobot.source_root),
        'lerobot.pi05_repo_root': _git_evidence(resources.lerobot.pi05_repo_root),
        'isaac.lab_root': _git_evidence(resources.isaac.lab_root),
        'utm.workspace_root': _git_evidence(resources.utm.workspace_root),
        'utm.yolo_model_path': _file_evidence(resources.utm.yolo_model_path),
    }
    versions = {}
    for name in ('ax4lab', 'botorch', 'gpytorch', 'torch', 'rtree'):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return {
        'schema': 'atr.installation_manifest.v1',
        'compatibility': 'unverified',
        'python': platform.python_version(), 'platform': platform.system(),
        'architecture': platform.machine(), 'packages': versions,
        'core_lock': _file_evidence(paths.runtime_root / 'uv.lock'),
        'external': selected,
        'profile_configured': profile.configured,
        'notes': ['Missing/unverified resources are not reproducibility evidence.',
                  'Model hashes identify local bytes, not provenance or license.',
                  'No device, GPU, ROS, or model execution was performed.'],
    }


def main() -> None:
    paths = current_paths()
    receipt = build_manifest(paths, load_installation_profile(paths))
    output = paths.repository_root / 'installation.manifest.local.json'
    # Replace atomically; never follow a pre-existing output symlink.
    descriptor, temporary = tempfile.mkstemp(prefix='.installation-manifest-', dir=output.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(receipt, stream, indent=2)
            stream.write('\n')
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print('Wrote sanitized installation.manifest.local.json (compatibility unverified).')


if __name__ == '__main__':
    main()
