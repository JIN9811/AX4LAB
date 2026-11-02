"""Single-host private JSON storage, published by atomic replacement."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile


class DesignError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Store:
    def __init__(self, root):
        self.path = Path(root) / 'state.json'
        try:
            self.data = json.loads(self.path.read_text()) if self.path.exists() else {
                'schema':'ax4lab.design_workspace.v1', 'profiles':{}, 'modules':{}, 'jobs':{}}
            if self.data.get('schema') != 'ax4lab.design_workspace.v1' or any(
                    not isinstance(self.data.get(key), dict) for key in ('profiles', 'modules', 'jobs')):
                raise ValueError('Invalid workspace store')
        except (OSError, ValueError) as exc:
            raise DesignError('store_invalid', 'Cannot read Design workspace store') from exc

    def save(self, data):
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', dir=self.path.parent, delete=False,
                                             encoding='utf-8', prefix='.state-') as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, allow_nan=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            self.data = deepcopy(data)
        except (OSError, ValueError) as exc:
            raise DesignError('store_write_failed', 'Cannot persist Design workspace state') from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
