"""Durable single-host Design workspace; expensive work uses the existing CPU pool."""
from concurrent.futures import TimeoutError as FutureTimeout
from copy import deepcopy
from pathlib import Path
import re
import threading
import uuid

from .catalog import DesignCatalog
from .engine import normalize_request, request_sha256
from .jobs import TERMINAL, contained, verify_receipt
from .profiles import DesignError, Store


class DesignService:
    def __init__(self, memory_root, artifact_root, *, catalog=None, executor=None, max_pending=2):
        if type(max_pending) is not int or not 1 <= max_pending <= 2:
            raise ValueError('Design supports one active and at most one queued job')
        self.catalog = catalog or DesignCatalog()
        self.store = Store(Path(memory_root)/'design_workspace')
        self.artifact_root = Path(artifact_root).absolute()/'design_workspace'
        self.executor = executor
        self.max_pending = max_pending
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.closed = False
        self.active = None
        self.cancellations = {}
        data = deepcopy(self.store.data)
        for job in data['jobs'].values():
            if job['state'] not in TERMINAL:
                job.update(state='interrupted', error={'code':'interrupted', 'message':'Host stopped; explicit new submission required'})
                job.pop('receipt', None)
        if data != self.store.data:
            self.store.save(data)
        self.thread = threading.Thread(target=self._run, name='design-job-coordinator', daemon=True)
        self.thread.start()

    def _lookup(self, kind, identity):
        try:
            return self.store.data[kind][identity]
        except (KeyError, TypeError):
            raise DesignError('not_found', 'Design item not found') from None

    @staticmethod
    def _revision(item, revision):
        if type(revision) is not int or revision != item['revision']:
            raise DesignError('revision_conflict', 'Stale or invalid revision')

    def _module(self, module_id):
        record = next((r for r in self.catalog.modules if r['id'] == module_id), None)
        if record is None:
            raise DesignError('module_unavailable', 'Module unavailable')
        return record

    def modules(self):
        with self.lock:
            return [dict(deepcopy(r['descriptor']), state=deepcopy(self.store.data['modules'].get(r['id'],
                {'enabled':True, 'revision':1})), icon_url=f"/api/design/modules/{r['id']}/icon") for r in self.catalog.modules]

    def geometries(self, module_id):
        with self.lock:
            self._module(module_id)
            return [deepcopy(r['descriptor']) for (m, _), r in self.catalog.geometries.items() if m == module_id]

    def icon(self, module_id):
        with self.lock:
            record = self._module(module_id)
            return contained(record['root'], record['icon_path'])

    def refresh(self):
        with self.lock:
            self.catalog = DesignCatalog(self.catalog.root)
            return {'modules':self.modules(), 'errors':deepcopy(self.catalog.errors)}

    def module_state(self, module_id, *, enabled=None, revision=None):
        with self.lock:
            self._module(module_id)
            current = self.store.data['modules'].get(module_id, {'enabled':True, 'revision':1})
            if enabled is None:
                return deepcopy(current)
            self._revision(current, revision)
            if type(enabled) is not bool:
                raise DesignError('invalid_request', 'enabled must be boolean')
            data = deepcopy(self.store.data)
            data['modules'][module_id] = {'enabled':enabled, 'revision':current['revision']+1}
            self.store.save(data)
            return deepcopy(data['modules'][module_id])

    def validate(self, request):
        with self.lock:
            try:
                normalized = normalize_request(request, self.catalog)
                record = self.catalog.resolve(normalized['module_id'], normalized['geometry_id'], normalized['provider_version'])
            except (ValueError, TypeError, KeyError) as exc:
                raise DesignError('invalid_request', str(exc)) from exc
            if not self.module_state(normalized['module_id'])['enabled']:
                raise DesignError('module_disabled', 'Module disabled for new requests')
            return {'ok':True, 'request':normalized, 'request_sha256':request_sha256(normalized),
                    'source_fingerprint':record['source_fingerprint']}

    def _profile_payload(self, payload):
        if not isinstance(payload, dict) or set(payload) != {'name', 'request'}:
            raise DesignError('invalid_request', 'Profile requires name and request')
        name = payload['name']
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            raise DesignError('invalid_request', 'Profile name must contain 1–120 characters')
        return {'name':name.strip(), 'request':self.validate(payload['request'])['request']}

    def create_profile(self, payload):
        with self.lock:
            profile = dict(self._profile_payload(payload), id=uuid.uuid4().hex, revision=1)
            data = deepcopy(self.store.data)
            data['profiles'][profile['id']] = profile
            self.store.save(data)
            return self.profile(profile['id'])

    def update_profile(self, profile_id, payload, revision):
        with self.lock:
            current = self._lookup('profiles', profile_id)
            self._revision(current, revision)
            profile = dict(self._profile_payload(payload), id=profile_id, revision=revision+1)
            data = deepcopy(self.store.data)
            data['profiles'][profile_id] = profile
            self.store.save(data)
            return self.profile(profile_id)

    def delete_profile(self, profile_id, revision, *, confirmed):
        with self.lock:
            self._revision(self._lookup('profiles', profile_id), revision)
            if confirmed is not True:
                raise DesignError('invalid_request', 'Please confirm profile deletion')
            data = deepcopy(self.store.data)
            del data['profiles'][profile_id]
            self.store.save(data)

    def profile(self, profile_id):
        with self.lock:
            result = deepcopy(self._lookup('profiles', profile_id))
            try:
                self.validate(result['request'])
                result['available'] = True
            except DesignError as exc:
                result.update(available=False, unavailable_reason=str(exc))
            return result

    def profiles(self):
        with self.lock:
            return [self.profile(key) for key in self.store.data['profiles']]

    def submit(self, request, *, idempotency_key):
        with self.condition:
            if self.closed:
                raise DesignError('unavailable', 'Design workspace is shutting down')
            if not isinstance(idempotency_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', idempotency_key):
                raise DesignError('invalid_request', 'Invalid idempotency key')
            # Exact raw retry remains recoverable even if its accepted provider was removed.
            existing = next((j for j in self.store.data['jobs'].values() if j['idempotency_key'] == idempotency_key), None)
            if existing and request == existing['submitted_request']:
                return self.job(existing['id'])
            validated = self.validate(request)
            if existing:
                if validated['request'] != existing['request']:
                    raise DesignError('idempotency_conflict', 'Conflicting idempotency key')
                return self.job(existing['id'])
            if self.executor is None:
                from utils.compute_pool import compute_enabled
                if not compute_enabled():
                    raise DesignError('compute_unavailable', 'CPU pool is not configured')
            pending = sum(j['state'] not in TERMINAL for j in self.store.data['jobs'].values())
            # A cancelled worker still occupies the active numerical slot until it returns.
            if self.active and self.store.data['jobs'][self.active]['state'] in TERMINAL:
                pending += 1
            if pending >= self.max_pending:
                raise DesignError('queue_full', 'Design job queue is full')
            job = {key:value for key, value in validated.items() if key != 'ok'}
            job.update(id=uuid.uuid4().hex, state='queued', idempotency_key=idempotency_key,
                       submitted_request=deepcopy(request), catalog_root=str(self.catalog.root))
            data = deepcopy(self.store.data)
            data['jobs'][job['id']] = job
            self.store.save(data)
            self.condition.notify_all()
            return self.job(job['id'])

    def job(self, job_id):
        with self.lock:
            result = deepcopy(self._lookup('jobs', job_id))
            for key in ('catalog_root', 'submitted_request', 'idempotency_key'):
                result.pop(key, None)
            if result['state'] == 'succeeded':
                result['artifact_urls'] = {key:f'/api/design/jobs/{job_id}/artifacts/{key}' for key in result['receipt']['artifacts']}
            return result

    def jobs(self):
        with self.lock:
            return [self.job(key) for key in self.store.data['jobs']]

    def cancel(self, job_id):
        with self.condition:
            job = self._lookup('jobs', job_id)
            if job['state'] not in TERMINAL:
                data = deepcopy(self.store.data)
                data['jobs'][job_id]['state'] = 'cancelled'
                self.store.save(data)
                if job_id in self.cancellations:
                    self.cancellations[job_id].set()
                self.condition.notify_all()
            return self.job(job_id)

    def artifact(self, job_id, artifact_id):
        with self.lock:
            job = self._lookup('jobs', job_id)
            if job['state'] != 'succeeded' or artifact_id != 'stl':
                raise DesignError('not_found', 'Artifact not available')
            return verify_receipt(job, self.artifact_root/job_id, job['receipt'])

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or any(j['state'] == 'queued' for j in self.store.data['jobs'].values()))
                if self.closed:
                    return
                job = deepcopy(next(j for j in self.store.data['jobs'].values() if j['state'] == 'queued'))
                self.active = job['id']
                cancelled = self.cancellations[job['id']] = threading.Event()
            root = self.artifact_root/job['id']
            try:
                with self.lock:
                    if self.store.data['jobs'][job['id']]['state'] == 'cancelled':
                        continue
                    data = deepcopy(self.store.data)
                    data['jobs'][job['id']]['state'] = 'running'
                    self.store.save(data)
                contained(self.artifact_root, root/'result')
                payload = {'request':job['request'], 'identity':{'job_id':job['id']},
                    'source_fingerprint':job['source_fingerprint'], 'catalog_root':job['catalog_root'],
                    'output_dir':str(root/'result')}
                if self.executor is None:
                    from utils.compute_pool import compute_submit
                    submit = compute_submit
                else:
                    submit = self.executor.submit
                future, _ = submit('geometry.design_generate', payload, timeout=300, cancellation=cancelled)
                while True:
                    try:
                        receipt = future.result(timeout=.1)
                        break
                    except FutureTimeout:
                        if future.done():
                            raise  # A completed worker's TimeoutError is not a polling timeout.
                        if self.closed:
                            raise DesignError('interrupted', 'Workspace shut down')
                verify_receipt(job, root, receipt)
                with self.lock:
                    if self.store.data['jobs'][job['id']]['state'] == 'cancelled':
                        self._discard_receipt(root)
                    else:
                        data = deepcopy(self.store.data)
                        data['jobs'][job['id']].update(state='succeeded', receipt=receipt)
                        self.store.save(data)
            except Exception as exc:
                self._discard_receipt(root)
                with self.lock:
                    data = deepcopy(self.store.data)
                    current = data['jobs'][job['id']]
                    if current['state'] != 'cancelled':
                        message = 'Artifact I/O failed' if isinstance(exc, OSError) else str(exc)
                        for private in (str(self.artifact_root), str(self.store.path.parent), job['catalog_root']):
                            message = message.replace(private, '[private]')
                        current.update(state='failed', error={'code':getattr(exc, 'code', 'job_failed'), 'message':message[:1000]})
                        current.pop('receipt', None)
                    try:
                        self.store.save(data)
                    except DesignError:
                        # Fail closed in memory. Old durable running state becomes interrupted on restart.
                        self.store.data = data
            finally:
                with self.condition:
                    self.active = None
                    self.cancellations.pop(job['id'], None)
                    self.condition.notify_all()

    def _discard_receipt(self, root):
        try:
            contained(self.artifact_root, root/'result/receipt.json').unlink(missing_ok=True)
        except (OSError, DesignError):
            pass  # Never expose a non-successful job, even when disk cleanup fails.

    def shutdown(self):
        with self.condition:
            self.closed = True
            for event in self.cancellations.values():
                event.set()
            self.condition.notify_all()
        self.thread.join(timeout=2)
