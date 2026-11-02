"""Discover trusted installed device folders, not browser-provided imports."""
from copy import deepcopy
from dataclasses import dataclass
import importlib.util
import math
from pathlib import Path
import re
import threading

import yaml

from .errors import SerialError

ID = re.compile(r'^[a-z][a-z0-9_]{0,63}$')


def contained(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or Path(relative).is_absolute():
        raise ValueError('Module asset escapes its directory')
    return path


@dataclass(frozen=True)
class DeviceModule:
    root: Path
    descriptor: dict


class ModuleCatalog:
    def __init__(self, root=None):
        self.root = Path(root or Path(__file__).parent / 'modules').resolve()
        self._modules = {}
        self._loaded = {}
        self._lock = threading.RLock()
        self.errors = []
        self.refresh()

    def refresh(self):
        found, errors, duplicates = {}, [], set()
        for file in sorted(self.root.glob('*/module.yaml')):
            try:
                root = file.parent.resolve()
                if not root.is_relative_to(self.root) or not file.resolve().is_relative_to(root):
                    raise ValueError('Module directory escapes catalog')
                d = yaml.safe_load(file.read_text(encoding='utf-8'))
                if not isinstance(d, dict) or d.get('schema') != 'ax4lab.serial_device.v1':
                    raise ValueError('Unsupported module schema')
                if not ID.fullmatch(str(d.get('id', ''))) or not re.fullmatch(r'\d+\.\d+\.\d+', str(d.get('version', ''))):
                    raise ValueError('Invalid module identity/version')
                if not isinstance(d.get('label'), str) or not d['label'].strip():
                    raise ValueError('Missing label')
                if not isinstance(d.get('defaults'), dict) or not isinstance(d.get('fields'), list) or not isinstance(d.get('channels'), list):
                    raise ValueError('Invalid settings/channel metadata')
                contained(root, d.get('icon', 'icon.svg'))
                if not contained(root, 'protocol.py').is_file():
                    raise ValueError('Missing protocol.py')
                keys = set()
                for field in d['fields']:
                    if not isinstance(field, dict) or not ID.fullmatch(str(field.get('key',''))) or field.get('type') not in {'number','select','port'}:
                        raise ValueError('Invalid field schema')
                    key = field['key']
                    if key in keys or key not in d['defaults'] or not isinstance(field.get('label'),str):
                        raise ValueError('Missing or duplicated field metadata')
                    keys.add(key)
                    if field['type']=='select' and (not isinstance(field.get('options'),list) or not field['options'] or d['defaults'][key] not in field['options']):
                        raise ValueError('Invalid field options/default')
                    if field['type']=='number':
                        values=[field.get('min'),field.get('max'),d['defaults'][key]]
                        if not all(type(v) in (int,float) and math.isfinite(v) for v in values) or not values[0]<=values[2]<=values[1]:
                            raise ValueError('Invalid numeric field bounds/default')
                common = {'port','baudrate','bytesize','parity','stopbits','flow_control','timeout_s','stale_after_s'}
                if not common <= keys or 'interval_s' not in d['defaults']:
                    raise ValueError('Missing common serial settings')
                if not isinstance(d.get('capabilities',[]),list) or set(d.get('capabilities',[]))-{'read','polling'}:
                    raise ValueError('Invalid capabilities')
                for channel in d['channels']:
                    if not isinstance(channel,dict) or not ID.fullmatch(str(channel.get('key',''))) or not isinstance(channel.get('label'),str):
                        raise ValueError('Invalid channel metadata')
                if d['id'] in found:
                    duplicates.add(d['id'])
                found[d['id']] = DeviceModule(root, d)
            except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
                errors.append({'module': file.parent.name, 'message': str(exc)})
        for identity in duplicates:
            found.pop(identity, None)
            errors.append({'module': identity, 'message': 'Duplicate module ID'})
        with self._lock:
            self._modules, self.errors = found, errors
        return self.list()

    def list(self):
        with self._lock:
            return [deepcopy(m.descriptor) for m in self._modules.values()]

    def get(self, identity):
        with self._lock:
            if identity not in self._modules:
                raise SerialError('module_unavailable', 'Module unavailable')
            return self._modules[identity]

    def icon(self, identity):
        m = self.get(identity)
        return contained(m.root, m.descriptor.get('icon','icon.svg'))

    def protocol(self, identity, variant=None):
        with self._lock:
            m = self.get(identity)
            path = contained(m.root, 'protocol.py')
            fingerprint = (str(path), path.stat().st_mtime_ns, m.descriptor['version'])
            if identity in self._loaded:
                previous, code = self._loaded[identity]
                if previous != fingerprint:
                    raise SerialError('module_changed', 'Restart server to apply updated protocol code')
            else:
                spec = importlib.util.spec_from_file_location(f'_serial_{identity}', path)
                code = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(code)
                self._loaded[identity] = fingerprint, code
            return code.create_protocol(variant or m.descriptor['defaults'].get('variant'))
