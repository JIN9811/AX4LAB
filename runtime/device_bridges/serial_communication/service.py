"""Host-independent serial service; all effects are explicit lifecycle calls."""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import threading

from .catalog import ModuleCatalog
from .errors import SerialError
from .profiles import ProfileStore
from .recording import Recording
from .session import Session
from .transport import enumerate_ports, open_transport


class SerialService:
    def __init__(self, config_path, log_root, *, catalog_root=None, port_provider=None, transport_factory=None):
        self.catalog = ModuleCatalog(catalog_root)
        self.store = ProfileStore(config_path)
        self.log_root = Path(log_root)
        self.port_provider = port_provider or enumerate_ports
        self.transport_factory = transport_factory or open_transport
        self.sessions = {}
        self.lock = threading.RLock()

    def profiles(self):
        result = self.store.list()
        ids = {m['id'] for m in self.catalog.list()}
        for p in result:
            p['module_available'] = p['module_id'] in ids
        return result

    def ports(self):
        ports = deepcopy(self.port_provider())
        with self.lock:
            for p in ports:
                for identity,s in self.sessions.items():
                    if s.state=='connected' and self._same_port(p,s.profile['settings']):
                        p.update(available=False, availability='owned', owner_profile_id=identity)
        return ports

    @staticmethod
    def _same_port(a,b):
        return ((a.get('device_id') and a.get('device_id')==b.get('device_id')) or
                os.path.realpath(a['port'])==os.path.realpath(b['port']))

    def _validated(self, data, old=None):
        module_id = data.get('module_id', (old or {}).get('module_id'))
        if old and module_id != old['module_id']:
            raise SerialError('invalid_config','Create a new profile to change module')
        descriptor = self.catalog.get(module_id).descriptor
        name = data.get('name',(old or {}).get('name',descriptor['label']))
        if not isinstance(name,str) or not 1<=len(name.strip())<=100:
            raise SerialError('invalid_config','Name must contain 1–100 characters')
        patch = data.get('settings',{})
        if not isinstance(patch,dict):
            raise SerialError('invalid_config','Settings must be an object')
        allowed = set(descriptor['defaults'])
        if set(patch)-allowed:
            raise SerialError('invalid_config','Unknown settings field')
        settings = {**descriptor['defaults'], **(old or {}).get('settings',{}), **patch}
        for f in descriptor['fields']:
            value = settings[f['key']]
            if f['type']=='select' and value not in f['options']:
                raise SerialError('invalid_config',f"Invalid {f['label']}")
            if f['type']=='number' and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not f['min']<=value<=f['max']):
                raise SerialError('invalid_config',f"Invalid {f['label']}")
        if not isinstance(settings['port'],str) or len(settings['port'])>512:
            raise SerialError('invalid_config','Invalid port')
        if 'port' in patch and settings['port']:
            matches = [p for p in self.port_provider() if p['port']==settings['port'] or p.get('stable_path')==settings['port']]
            if len(matches)==1:
                previous = (old or {}).get('settings',{})
                if (settings['port']==previous.get('port') and previous.get('device_id')
                        and matches[0].get('device_id')!=previous['device_id']):
                    raise SerialError('port_identity_changed','A different device now uses this port; create a new profile for it')
                settings['device_id'] = matches[0].get('device_id')
                settings['stable_path'] = matches[0].get('stable_path',matches[0]['port'])
            elif not old or settings['port'] != old['settings']['port']:
                raise SerialError('port_unavailable','Choose a detected port')
        elif 'port' in patch and not settings['port']:
            settings.pop('device_id',None)
            settings.pop('stable_path',None)
        return {'name':name.strip(),'module_id':module_id,'settings':settings}

    def create_profile(self,data):
        with self.lock:
            return self.store.create(self._validated(data))

    def update_profile(self,identity,data,revision):
        with self.lock:
            return self.store.update(identity,self._validated(data,self.store.get(identity)),revision)

    def delete_profile(self,identity,revision):
        with self.lock:
            if identity in self.sessions and self.sessions[identity].state=='connected':
                raise SerialError('busy','Disconnect before deleting the profile')
            self.store.delete(identity,revision)
            if identity in self.sessions:
                self.sessions.pop(identity).close()

    def connect(self,identity):
        with self.lock:
            p = self.store.get(identity)
            if identity in self.sessions:
                if self.sessions[identity].state=='connected':
                    return self.status(identity)
                self.sessions.pop(identity).close()
            d = self.catalog.get(p['module_id']).descriptor
            settings = p['settings']
            if not settings.get('port'):
                raise SerialError('port_unavailable','Select a port and press Set first')
            choices = self.port_provider()
            if settings.get('device_id'):
                choices = [x for x in choices if x.get('device_id')==settings['device_id']]
            else:
                choices = [x for x in choices if x['port']==settings['port']]
            if len(choices)!=1 or not choices[0].get('available',True):
                raise SerialError('port_unavailable','Saved device is unavailable or ambiguous')
            active = deepcopy(p)
            active['settings']['port'] = choices[0]['port']
            for s in self.sessions.values():
                if s.state=='connected' and self._same_port(choices[0],s.profile['settings']):
                    raise SerialError('port_busy','Port already belongs to another profile')
            parser = self.catalog.protocol(p['module_id'],settings.get('variant'))
            transport = self.transport_factory(active['settings'])
            try:
                self.sessions[identity] = Session(active,d,transport,parser,self.log_root)
            except Exception:
                transport.close()
                raise
            return self.status(identity)

    def disconnect(self,identity):
        with self.lock:
            self.store.get(identity)
            if identity in self.sessions:
                self.sessions[identity].close()
            return self.status(identity)

    def _session(self,identity):
        with self.lock:
            self.store.get(identity)
            if identity not in self.sessions:
                raise SerialError('disconnected','Connect first')
            return self.sessions[identity]

    def status(self,identity):
        with self.lock:
            p = self.store.get(identity)
            if identity in self.sessions:
                result = self.sessions[identity].snapshot()
                result['needs_reconnect'] = result['active_revision'] != p['revision']
            else:
                result = {'state':'disconnected','receive_state':'no_data','needs_reconnect':False,
                          'recording':None,'polling':False,'rx_bytes':0,'tx_bytes':0,'parse_errors':0}
            return {'schema':'ax4lab.serial_status.v1','profile_id':identity,'saved_revision':p['revision'],**result}

    def latest(self,identity):
        status = self.status(identity)
        with self.lock:
            s = self.sessions.get(identity)
        with s.cv if s else threading.RLock():
            value = deepcopy(s.measurement) if s else None
        return {'measurement':value,'age_s':status.get('age_s'),
                'stale':status['receive_state']=='stale','state':status['state']}

    def events(self,identity,after=0):
        self.store.get(identity)
        with self.lock:
            s = self.sessions.get(identity)
        return s.events(after) if s else {'session_id':None,'cursor':0,'gap':False,'events':[]}

    def read(self,identity,timeout_s=None):
        s = self._session(identity)
        value = timeout_s if timeout_s is not None else s.profile['settings']['timeout_s']
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not .1<=value<=30:
            raise SerialError('invalid_config','Timeout must be 0.1–30 seconds')
        return s.read(value)

    def polling(self,identity,enabled,interval_s=1):
        if not isinstance(enabled,bool) or not isinstance(interval_s,(int,float)) or not math.isfinite(interval_s) or not .2<=interval_s<=3600:
            raise SerialError('invalid_config','Interval must be 0.2–3600 seconds')
        with self.lock:
            self._session(identity).polling(enabled,interval_s)
        return self.status(identity)

    def record(self,identity,enabled):
        with self.lock:
            return self._session(identity).record(enabled)

    def recordings(self):
        rows = []
        for p in sorted(self.log_root.glob('*/manifest.json'),reverse=True):
            if re.fullmatch('[a-f0-9]{32}',p.parent.name) and p.resolve().is_relative_to(self.log_root.resolve()):
                try:
                    rows.append(json.loads(p.read_text()))
                except (OSError,ValueError):
                    continue
        return sorted(rows,key=lambda r:r.get('started_at',0),reverse=True)

    def recording_file(self,identity,name):
        if not re.fullmatch('[a-f0-9]{32}',identity) or name not in Recording.FILES:
            raise SerialError('not_found','Recording file not found')
        path = (self.log_root/identity/name).resolve()
        if not path.is_relative_to(self.log_root.resolve()) or not path.is_file():
            raise SerialError('not_found','Recording file not found')
        return path

    def shutdown(self):
        with self.lock:
            for s in self.sessions.values():
                s.close()
            self.sessions.clear()
