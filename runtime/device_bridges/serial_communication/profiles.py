"""Versioned private configuration; never silently replace corrupt files."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import threading
from uuid import uuid4

from .errors import SerialError


def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.'+path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class ProfileStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()

    def _read(self):
        if not self.path.exists():
            return {'schema': 'ax4lab.serial_profiles.v1', 'profiles': {}}
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('schema') != 'ax4lab.serial_profiles.v1' or not isinstance(data.get('profiles'), dict):
                raise ValueError('Invalid profile schema')
            for key, p in data['profiles'].items():
                if not isinstance(p, dict) or p.get('id') != key or not isinstance(p.get('revision'), int) or not isinstance(p.get('settings'), dict):
                    raise ValueError('Invalid profile record')
            return data
        except (OSError, ValueError, AttributeError) as exc:
            raise SerialError('config_invalid', 'Saved serial config cannot be read; original retained') from exc

    def list(self):
        with self.lock:
            return list(self._read()['profiles'].values())

    def get(self, identity):
        with self.lock:
            try:
                return self._read()['profiles'][identity]
            except KeyError:
                raise SerialError('not_found', 'Profile not found') from None

    def _save(self, data):
        try:
            atomic_json(self.path, data)
        except OSError as exc:
            raise SerialError('config_write_failed', 'Config was not saved') from exc

    def create(self, data):
        with self.lock:
            state = self._read()
            p = {**deepcopy(data), 'id': uuid4().hex, 'revision': 1}
            state['profiles'][p['id']] = p
            self._save(state)
            return p

    def update(self, identity, data, revision):
        with self.lock:
            state = self._read()
            old = self.get(identity)
            if revision != old['revision']:
                raise SerialError('revision_conflict', 'Config revision changed; reload before Set')
            p = {**old, **deepcopy(data), 'id': identity, 'revision': revision+1}
            state['profiles'][identity] = p
            self._save(state)
            return p

    def delete(self, identity, revision):
        with self.lock:
            state = self._read()
            if self.get(identity)['revision'] != revision:
                raise SerialError('revision_conflict', 'Config revision changed')
            del state['profiles'][identity]
            self._save(state)
