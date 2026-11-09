"""Discover trusted installed device folders, not browser-provided imports."""
from copy import deepcopy
from dataclasses import dataclass
import importlib.util
import math
from pathlib import Path
import re
import threading

from workspaces.catalog import discover_modules

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


def _validate_serial_descriptor(d):
    if not isinstance(d, dict) or d.get('schema') != 'ax4lab.serial_device.v1':
        raise ValueError('Unsupported module schema')
    if not ID.fullmatch(str(d.get('id', ''))) or not re.fullmatch(r'\d+\.\d+\.\d+', str(d.get('version', ''))):
        raise ValueError('Invalid module identity/version')
    if not isinstance(d.get('label'), str) or not d['label'].strip():
        raise ValueError('Missing label')
    if not isinstance(d.get('defaults'), dict) or not isinstance(d.get('fields'), list) or not isinstance(d.get('channels'), list):
        raise ValueError('Invalid settings/channel metadata')
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
    views = d.get('views', [])
    if not isinstance(views, list):
        raise ValueError('Invalid view metadata')
    view_ids = set()
    for view in views:
        if (not isinstance(view, dict) or set(view) != {'id', 'label'}
                or not ID.fullmatch(str(view.get('id', '')))
                or not isinstance(view.get('label'), str) or not view['label'].strip()
                or view['id'] in view_ids):
            raise ValueError('Invalid or duplicate view metadata')
        view_ids.add(view['id'])
    d['__provider_file__'] = 'protocol.py'
    return d


class ModuleCatalog:
    def __init__(self, root=None):
        self.root = Path(root or Path(__file__).parent / 'modules').resolve()
        self._modules = {}
        self._loaded = {}
        self._lock = threading.RLock()
        self.errors = []
        self.refresh()

    def refresh(self):
        records, errors = discover_modules(self.root, _validate_serial_descriptor)
        found = {}
        for record in records:
            try:
                for view in record['descriptor'].get('views', []):
                    entry = contained(record['root'], 'views/'+view['id']+'/index.html')
                    if not entry.is_file():
                        raise ValueError('Missing view entry: '+view['id'])
                found[record['id']] = DeviceModule(record['root'], record['descriptor'])
            except (ValueError, OSError) as exc:
                errors.append({'module':record['id'], 'message':str(exc)})
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

    def view_file(self, identity, view_id, asset='index.html'):
        m = self.get(identity)
        if view_id not in {view['id'] for view in m.descriptor.get('views', [])}:
            raise SerialError('not_found', 'Module view unavailable')
        try:
            root = contained(m.root, 'views/'+view_id)
            path = contained(root, asset)
            if not path.is_file():
                raise ValueError('Missing view asset')
            return path
        except (ValueError, OSError) as exc:
            raise SerialError('not_found', 'Module view asset unavailable') from exc

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
