"""Receipt verification; no numerical work runs in this module."""
import hashlib
import json
from pathlib import Path

from .engine import request_sha256
from .profiles import DesignError

TERMINAL = {'succeeded', 'failed', 'cancelled', 'interrupted'}


def contained(root, path):
    root, path = Path(root).absolute(), Path(path).absolute()
    if not path.is_relative_to(root) or any(p.is_symlink() for p in (path, *path.parents)):
        raise DesignError('artifact_invalid', 'Artifact containment violation')
    return path


def verify_receipt(job, root, receipt):
    try:
        return _verify_receipt(job, root, receipt)
    except DesignError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise DesignError('artifact_invalid', 'Artifact or receipt is missing or unreadable') from exc


def _verify_receipt(job, root, receipt):
    if (not isinstance(receipt, dict) or receipt.get('schema') != 'ax4lab.geometry_receipt.v1'
            or receipt.get('ok') is not True or receipt.get('request') != job['request']
            or receipt.get('request_sha256') != request_sha256(job['request'])
            or receipt.get('source_fingerprint') != job['source_fingerprint']
            or receipt.get('identity') != {'job_id':job['id']}):
        raise DesignError('artifact_invalid', 'Worker receipt does not match accepted job')
    receipt_path = contained(root, root/'result/receipt.json')
    if json.loads(receipt_path.read_text()) != receipt:
        raise DesignError('artifact_invalid', 'Stored receipt mismatch')
    artifacts = receipt.get('artifacts')
    if not isinstance(artifacts, dict) or set(artifacts) != {'stl'}:
        raise DesignError('artifact_invalid', 'Missing STL artifact')
    item = artifacts['stl']
    if item.get('basename') != 'geometry.stl':
        raise DesignError('artifact_invalid', 'Unexpected artifact basename')
    file = contained(root, root/'result/geometry.stl')
    digest = hashlib.sha256()
    with file.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    if file.stat().st_size != item.get('size_bytes') or digest.hexdigest() != item.get('sha256'):
        raise DesignError('artifact_invalid', 'Artifact file hash mismatch')
    return file
